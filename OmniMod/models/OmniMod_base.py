import logging
import random

import torch
from torch.cuda.amp import autocast as autocast
import torch.nn as nn

from OmniMod.common.registry import registry
from OmniMod.models.base_model import BaseModel
from transformers import StoppingCriteria, StoppingCriteriaList

from OmniMod.conversation.conversation import StoppingCriteriaSub

class OmniModBase(BaseModel):
    """
    Base class for OmniModBase
    """

    def __init__(
        self,
        vision_model="eva_clip_g",
        audio_model="whisper",
        img_size=224,
        drop_path_rate=0,
        use_grad_checkpoint=False,
        precision="fp16",
        freeze_vision=True,
        freeze_audio=True,
        language_model="",
        max_txt_len=32,
        max_context_len=3800,
        prompt_template="",
        end_sym='\n',
        low_resource=False,  # use 8 bit and put vit in cpu
        device_8bit=0,  # the device of 8bit model should be set when loading and cannot be changed anymore.
        lora_r=0,  # lora_r means lora is not used
        bits=8,
        lora_target_modules=["q_proj", "v_proj"],
        lora_alpha=16,
        lora_dropout=0.05,
    ):
        super().__init__()

        self.language_model, self.language_tokenizer = self.init_llm(
            language_model_path=language_model,
            bits=bits,
            low_resource=low_resource,
            low_res_device=device_8bit,
            lora_r=lora_r,
            lora_target_modules=lora_target_modules,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
        )

        self.visual_encoder, self.ln_vision, self.num_concat = self.init_vision_encoder(
            vision_model,
            freeze_vision, 
            img_size=img_size, 
            drop_path_rate=drop_path_rate, 
            use_checkpoint=use_grad_checkpoint, 
            precision=precision
        )

        self.audio_encoder = self.init_audio_encoder(
            audio_model,
            freeze_audio,
            precision=precision
        )

        self.max_txt_len = max_txt_len
        self.max_context_len = max_context_len
        self.end_sym = end_sym

        self.prompt_template = prompt_template
        self.prompt_list = []

    def vit_to_cpu(self):
        self.ln_vision.to("cpu")
        self.ln_vision.float()
        self.visual_encoder.to("cpu")
        self.visual_encoder.float()

    def get_context_emb(self, prompt, img_list, audio=None):
        device = img_list[0].device
        prompt_segs = prompt.split('<ImageHere>')
        assert len(prompt_segs) == len(img_list) + 1, "Unmatched numbers of image placeholders and images."
        seg_tokens = [
            self.language_tokenizer(
                seg, return_tensors="pt", add_special_tokens=i==0).to(device).input_ids # only add bos to the first seg
            for i, seg in enumerate(prompt_segs)
        ]
        seg_embs = [self.embed_tokens(seg_t) for seg_t in seg_tokens]

        # mixed_embs = [emb for pair in zip(seg_embs[:-1], img_list) for emb in pair] + [seg_embs[-1], audio[0].to(self.device)] # [audio]
        # mixed_embs = torch.cat(mixed_embs, dim=1)

        # Interleave segment embeddings with image embeddings
        mixed_embs = [emb for pair in zip(seg_embs[:-1], img_list) for emb in pair] + [seg_embs[-1]]
        
        # Handle audio: append only if audio is not None
        if audio is not None:
            mixed_embs.append(audio[0].to(device))
        
        # Concatenate along the appropriate dimension
        mixed_embs = torch.cat(mixed_embs, dim=1)
        return mixed_embs
        
    def prompt_wrap(self, img_embeds, audio_embeds, img_atts, prompts, lengths=None):
        if prompts is None or len(prompts) == 0:
            # print("Prompt case")
            # If prompts are not provided, combine image and audio embeddings if available
            if img_embeds is not None and audio_embeds is not None:
                combined_embeds = []
                for img_embed, audio_embed in zip(img_embeds, audio_embeds):
                    combined = torch.cat([img_embed, audio_embed.unsqueeze(0)], dim=1)
                    combined_embeds.append(combined)
                
                emb_lens = [emb.shape[1] for emb in combined_embeds]
                pad_emb = self.embed_tokens(torch.tensor(self.language_tokenizer.pad_token_id, device=img_embeds.device))
                
                max_length = max(emb_lens) if max(emb_lens) < self.max_context_len else self.max_context_len
                wrapped_embs = pad_emb.expand(len(emb_lens), max_length, -1).clone()
                wrapped_atts = torch.zeros([len(emb_lens), max_length], dtype=torch.int, device=img_embeds.device)
                
                for i, emb in enumerate(combined_embeds):
                    length = emb_lens[i] if emb_lens[i] < self.max_context_len else self.max_context_len
                    wrapped_embs[i, :length] = emb[:, :length]
                    wrapped_atts[i, :length] = 1
                return wrapped_embs, wrapped_atts
            
            # If only image embeddings are available
            return img_embeds, img_atts

        # if prompts is None or len(prompts) == 0:
        #     # prompts is not provided, just return the original image embedding
        #     return img_embeds, img_atts
        elif img_embeds is None:
            # prompt is provided but there is no image embedding. return the prompt embedding in right padding
            self.language_tokenizer.padding_side = "right"
            prompt_tokens = self.language_tokenizer(
                prompts,
                return_tensors="pt",
                padding="longest",
                add_special_tokens=False
            ).to(self.device)
            prompt_embeds = self.embed_tokens(prompt_tokens.input_ids)
            atts_prompt = prompt_tokens.attention_mask
            return prompt_embeds, atts_prompt
        else:
            # return the multi-modal embedding in right padding
            emb_lists = []
            if isinstance(prompts, str):
                prompts = [prompts] * len(img_embeds)

            if audio_embeds is None:

                for idx, (each_img_embed, each_prompt) in enumerate(zip(img_embeds, prompts)):
                    pn = each_img_embed.shape[-2]
                    if lengths is not None:
                        each_img_embed = each_img_embed.reshape(-1, each_img_embed.shape[-1])
                        each_img_embed = each_img_embed[:lengths[idx] * pn]
                    p_segs = each_prompt.split('<ImageHere>')
                    interleave_emb = []
                    for idx, seg in enumerate(p_segs[:-1]):
                        p_tokens = self.language_tokenizer(
                            seg, return_tensors="pt", add_special_tokens=False).to(img_embeds.device)
                        p_embed = self.embed_tokens(p_tokens.input_ids)
                        interleave_emb.append(torch.cat([p_embed, each_img_embed[None][:, idx * pn:(idx + 1) * pn]], dim=1))
                    wrapped_emb = torch.cat(interleave_emb, dim=1)
                    p_tokens = self.language_tokenizer(
                        p_segs[-1], return_tensors="pt", add_special_tokens=False).to(img_embeds.device)
                    p_embed = self.embed_tokens(p_tokens.input_ids)
                    wrapped_emb = torch.cat([wrapped_emb, p_embed], dim=1)
                    emb_lists.append(wrapped_emb)
            else:
                
                for idx, (each_img_embed, each_prompt, each_audio_embed) in enumerate(zip(img_embeds, prompts, audio_embeds)):
                    pn = each_img_embed.shape[-2]
                    # aund = each_audio_embed.shape[-2]
                    # each_audio_embed = each_audio_embed.unsqueeze(0)

                    # print('Each sample: ', each_img_embed, each_prompt, each_audio_embed)
                    # print('pn: ', pn, 'aund: ', aund)
                    if lengths is not None:
                        each_img_embed = each_img_embed.reshape(-1, each_img_embed.shape[-1])
                        each_img_embed = each_img_embed[:lengths[idx] * pn]
                    p_segs = each_prompt.split('<ImageHere>')
                    interleave_emb = []
                    # print('p_segs: ', p_segs)

                    for inner_idx, seg in enumerate(p_segs[:-1]):
                        # print('seg: ', seg)
                        # print('each_img_embed[None][:, idx * pn:(idx + 1) * pn]: ', each_img_embed[None][:, idx * pn:(idx + 1) * pn])
                        p_tokens = self.language_tokenizer(seg, return_tensors="pt", add_special_tokens=False).to(img_embeds.device)
                        p_embed = self.embed_tokens(p_tokens.input_ids)
                        # print('Shape: ', p_embed.shape, each_img_embed[None][:, idx * pn:(idx + 1) * pn].shape, each_audio_embed.shape)
                        interleave_emb.append(torch.cat([p_embed, each_img_embed[None][:, inner_idx * pn:(inner_idx + 1) * pn]], dim=1))

                        # interleave_emb.append(torch.cat([p_embed, each_img_embed[None][:, idx * pn:(idx + 1) * pn], each_audio_embed], dim=1))
                    wrapped_emb = torch.cat(interleave_emb, dim=1)
                    p_tokens = self.language_tokenizer(p_segs[-1], return_tensors="pt", add_special_tokens=False).to(img_embeds.device)
                    p_embed = self.embed_tokens(p_tokens.input_ids)

                    each_audio_embed = each_audio_embed.unsqueeze(0)
                    # print('Shape: ', wrapped_emb.shape, p_embed.shape, each_audio_embed.shape)

                    # each_audio_embed will be of shape [1, audio_embedding_dim]
                    if each_audio_embed is None:
                        wrapped_emb = torch.cat([wrapped_emb, p_embed], dim=1)
                    else:
                        wrapped_emb = torch.cat([wrapped_emb, p_embed, each_audio_embed], dim=1)
                    
                    emb_lists.append(wrapped_emb)

            emb_lens = [emb.shape[1] for emb in emb_lists]
            pad_emb = self.embed_tokens(torch.tensor(self.language_tokenizer.pad_token_id, device=img_embeds.device))

            max_length = max(emb_lens) if max(emb_lens) < self.max_context_len else self.max_context_len
            wrapped_embs = pad_emb.expand(len(emb_lens), max_length, -1).clone()
            wrapped_atts = torch.zeros([len(emb_lens), max_length], dtype=torch.int, device=img_embeds.device)
            
            for i, emb in enumerate(emb_lists):
                length = emb_lens[i] if emb_lens[i] < self.max_context_len else self.max_context_len
                wrapped_embs[i, :length] = emb[:, :length]
                wrapped_atts[i, :length] = 1
            return wrapped_embs, wrapped_atts

    def concat_emb_input_output(self, input_embs, input_atts, output_embs, output_atts):
        """
        Concatenate the batched input embedding and batched output embedding together.
        Both the input and the output embedding should be right padded.
        """
        input_lens = []
        cat_embs = []
        cat_atts = []
        for i in range(input_embs.size(0)):
            input_len = input_atts[i].sum()
            input_lens.append(input_len)
            cat_embs.append(
                torch.cat([
                    input_embs[i][:input_len],
                    output_embs[i],
                    input_embs[i][input_len:]
                ])
            )
            cat_atts.append(
                torch.cat([
                    input_atts[i][:input_len],
                    output_atts[i],
                    input_atts[i][input_len:]
                ])
            )
        cat_embs = torch.stack(cat_embs)
        cat_atts = torch.stack(cat_atts)
        return cat_embs, cat_atts, input_lens

    def tokenize_conversation(self, conv_q, conv_a):
        """concatenate conversation and make sure the model is only trained to regress the answer"""

        to_regress_token_ids_list = []
        targets_list = []

        batch_size = len(conv_q)
        for batch_idx in range(batch_size):
            questions, answers = conv_q[batch_idx], conv_a[batch_idx]
            questions = [self.language_tokenizer(self.language_tokenizer.bos_token + q,
                                              return_tensors="pt",
                                              add_special_tokens=False).to(self.device) for q in questions[1:]]  # the first question is handled in the prompt wrap function, skip it
            answers = [self.language_tokenizer(a + self.end_sym,
                                            return_tensors="pt",
                                            add_special_tokens=False).to(self.device) for a in answers]
            cur_id = []
            cur_target = []
            for i in range(len(questions)):
                cur_id.append(answers[i].input_ids)
                cur_target.append(answers[i].input_ids)
                cur_id.append(questions[i].input_ids)
                cur_target.append(torch.ones_like(questions[i].input_ids) * -100)

            cur_id.append(answers[-1].input_ids)
            cur_target.append(answers[-1].input_ids)

            cur_id = torch.cat(cur_id, dim=1)
            cur_target = torch.cat(cur_target, dim=1)
            to_regress_token_ids_list.append(cur_id)
            targets_list.append(cur_target)

        max_len = min(max([target.shape[1] for target in targets_list]), self.max_txt_len)
        to_regress_token_ids = torch.ones([batch_size, max_len],
                                          dtype=cur_id.dtype, device=self.device) * self.language_tokenizer.pad_token_id
        targets = torch.ones([batch_size, max_len],
                                          dtype=cur_id.dtype, device=self.device) * -100
        for batch_idx in range(batch_size):
            cur_len = to_regress_token_ids_list[batch_idx].shape[1]
            to_regress_token_ids[batch_idx, :cur_len] = to_regress_token_ids_list[batch_idx][0, :max_len]
            targets[batch_idx, :cur_len] = targets_list[batch_idx][0, :max_len]

        to_regress_token_attn = (to_regress_token_ids != self.language_tokenizer.pad_token_id).to(torch.int)

        return to_regress_token_ids, to_regress_token_attn, targets

    def preparing_embedding(self, samples):
        ### prepare input tokens
        if "audio" in samples and "instruction_input" in samples:
            # for instruction_input in samples["instruction_input"]:
            #     if not instruction_input.endswith("<Img><ImageHere></Img>"):
            #         raise ValueError("You cannot specify both audio and instruction_input at the same time")
            audio_embeds, audio_atts = self.encode_audio(samples["audio"])

        else:
            audio_embeds, audio_atts = None, None

        if 'image' in samples:
            img_embeds, img_atts = self.encode_img(samples["image"])
        else:
            img_embeds = img_atts = None

        if 'conv_q' in samples:
            # handeling conversation datasets
            conv_q, conv_a = samples['conv_q'], samples['conv_a']

            connect_sym = samples['connect_sym'][0]
            conv_q = [q.split(connect_sym)for q in conv_q]
            conv_a = [a.split(connect_sym) for a in conv_a]

            conv_q = [[self.prompt_template.format(item) for item in items] for items in conv_q]

            cond_embeds, cond_atts = self.prompt_wrap(img_embeds, img_atts, [q[0] for q in conv_q])
            regress_token_ids, regress_atts, part_targets = self.tokenize_conversation(conv_q, conv_a)

        else:
            if "instruction_input" in samples:
                instruction = samples["instruction_input"]
            elif self.prompt_list:
                instruction = random.choice(self.prompt_list)
            else:
                instruction = None

            if hasattr(self, 'chat_template') and self.chat_template:
                instruction = [self.prompt_template.format(instruct) for instruct in instruction]
            # print('output shapes: ', len(img_embeds), len(audio_embeds), len(img_atts), len(instruction))
            # print('output shapes: ', img_embeds[0], audio_embeds[0], img_atts[0], instruction[0])
            if 'length' in samples:
                # the input is a image train (like videos)
                bsz, pn, hs = img_embeds.shape
                img_embeds = img_embeds.reshape(len(samples['image']), -1, pn, hs)
                cond_embeds, cond_atts = self.prompt_wrap(img_embeds, audio_embeds, img_atts, instruction, samples['length'])
            else:
                # print('Our input: ', img_embeds, audio_embeds, img_atts, instruction)
                cond_embeds, cond_atts = self.prompt_wrap(img_embeds, audio_embeds, img_atts, instruction)

            ### prepare target tokens
            self.language_tokenizer.padding_side = "right"
            text = [t + self.end_sym for t in samples["answer"]]

            regress_tokens = self.language_tokenizer(
                text,
                return_tensors="pt",
                padding="longest",
                truncation=True,
                max_length=self.max_txt_len,
                add_special_tokens=False
            ).to(self.device)

            regress_token_ids = regress_tokens.input_ids
            regress_atts = regress_tokens.attention_mask
            part_targets = regress_token_ids.masked_fill(
                regress_token_ids == self.language_tokenizer.pad_token_id, -100
            )

        regress_embeds = self.embed_tokens(regress_token_ids)

        return cond_embeds, cond_atts, regress_embeds, regress_atts, part_targets

    def forward(self, samples, reduction='mean'):
        # prepare the embedding to condition and the embedding to regress
        cond_embeds, cond_atts, regress_embeds, regress_atts, part_targets = \
            self.preparing_embedding(samples)

        # concat the embedding to condition and the embedding to regress
        inputs_embeds, attention_mask, input_lens = \
            self.concat_emb_input_output(cond_embeds, cond_atts, regress_embeds, regress_atts)

        # get bos token embedding
        bos = torch.ones_like(part_targets[:, :1]) * self.language_tokenizer.bos_token_id
        bos_embeds = self.embed_tokens(bos)
        bos_atts = cond_atts[:, :1]

        # add bos token at the begining
        inputs_embeds = torch.cat([bos_embeds, inputs_embeds], dim=1)
        attention_mask = torch.cat([bos_atts, attention_mask], dim=1)

        # ensemble the final targets
        targets = torch.ones([inputs_embeds.shape[0], inputs_embeds.shape[1]],
                             dtype=torch.long).to(self.device).fill_(-100)

        for i, target in enumerate(part_targets):
            targets[i, input_lens[i]+1:input_lens[i]+len(target)+1] = target  # plus 1 for bos

        with self.maybe_autocast():
            outputs = self.language_model(
                inputs_embeds=inputs_embeds,
                attention_mask=attention_mask,
                return_dict=True,
                labels=targets,
                reduction=reduction
            )
        loss = outputs.loss

        return {"loss": loss}

    def embed_tokens(self, token_ids):
        if hasattr(self.language_model.base_model, 'model'): ## lora wrapped model
            embeds = self.language_model.base_model.model.model.embed_tokens(token_ids)
        else:
            embeds = self.language_model.base_model.embed_tokens(token_ids)
        return embeds

    @torch.no_grad()
    def generate(
        self,
        images=None,
        audios=None,
        texts=None,
        num_beams=1,
        max_new_tokens=20,
        min_length=1,
        top_p=0.9,
        repetition_penalty=1,
        length_penalty=1,
        temperature=1,
        do_sample=False,
        stop_words_ids=[2],
    ):
        '''
            function for generate test use
        '''
        # if audios is not None and texts is not None:
        #     for text in texts:
        #         if not text.endswith("<Img><ImageHere></Img> [/INST]"):
        #             raise ValueError("You cannot specify both audio and texts at the same time")
                
        if images is not None and texts is None:
            raise ValueError("You must specify <Img><ImageHere></Img> in the text")
        
        stopping_criteria = StoppingCriteriaList([StoppingCriteriaSub(
            stops=[torch.tensor([i]).to(self.device) for i in stop_words_ids])])

        # img_embeds, atts_img = self.encode_img(images.to(self.device))

        # image_lists = [[image_emb[None]] for image_emb in img_embeds]

        # audio_embeds, atts_audio = self.encode_audio(audios.to(self.device))
        # audio_embeds = [[audio_embed[None]] for audio_embed in audio_embeds]

        # batch_embs = [self.get_context_emb(text, img_list, audio_embed) for text, img_list, audio_embed in zip(texts, image_lists, audio_embeds)]
        
        # Process images
        img_embeds, atts_img = self.encode_img(images.to(self.device)) if images is not None else (None, None)
        image_lists = [[image_emb[None]] for image_emb in img_embeds] if img_embeds is not None else None

        # Process audios only if audios are provided
        if audios is not None:
            audio_embeds, atts_audio = self.encode_audio(audios.to(self.device))
            audio_embeds = [[audio_embed[None]] for audio_embed in audio_embeds]
        else:
            audio_embeds = [None] * len(texts)  # Handle the case where audios is None

        # Generate batch embeddings
        batch_embs = [self.get_context_emb(text, img_list, audio_embed)
                    for text, img_list, audio_embed in zip(texts, image_lists, audio_embeds)]

        batch_size = len(batch_embs)
        max_len = max([emb.shape[1] for emb in batch_embs])
        emb_dim = batch_embs[0].shape[2]
        dtype = batch_embs[0].dtype
        device = batch_embs[0].device

        embs = torch.zeros([batch_size, max_len, emb_dim], dtype=dtype, device=device)
        attn_mask = torch.zeros([batch_size, max_len], dtype=torch.int, device=device)
        for i, emb in enumerate(batch_embs):
            emb_len = emb.shape[1]
            embs[i, -emb_len:] = emb[0]
            attn_mask[i, -emb_len:] = 1

        with self.maybe_autocast():
            outputs = self.language_model.generate(
                inputs_embeds=embs,
                attention_mask=attn_mask,
                max_new_tokens=max_new_tokens,
                num_beams=num_beams,
                length_penalty=length_penalty,
                temperature=temperature,
                do_sample=do_sample,
                min_length=min_length,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                # stopping_criteria=stopping_criteria,
            )

        # with self.maybe_autocast():
        #     outputs = self.language_model.generate(
        #         inputs_embeds=embs,
        #         attention_mask=attn_mask,
        #         max_new_tokens=max_new_tokens,
        #         num_beams=num_beams,
        #         do_sample=do_sample,
        #         # stopping_criteria=stopping_criteria,
        #     )
        answers = []
        for output_token in outputs:
            if output_token[0] == 0:
                output_token = output_token[1:]
            output_texts = self.language_tokenizer.decode(output_token, skip_special_tokens=True)
            output_texts = output_texts.split('</s>')[0]  # remove the stop sign </s>
            output_texts = output_texts.replace("<s>", "")
            output_texts = output_texts.split(r'[/INST]')[-1].strip()
            answers.append(output_texts)

        return answers

    @torch.no_grad()
    def multi_select(self, images, texts, answers, num_cand=None):
        all_losses = []
        for answer in answers:
            choice_samples = {
                'image': images,
                'instruction_input': texts,
                'answer': answer
            }
            loss = self.forward(choice_samples, reduction='none')['loss'].reshape(-1, 1)
            all_losses.append(loss)
            torch.cuda.empty_cache()
        all_losses = torch.cat(all_losses, dim=-1)
        if num_cand is not None:
            for i in range(all_losses.shape[0]):
                all_losses[i, num_cand[i]:] = 9999
        output_class_ranks = torch.argsort(all_losses, dim=-1)
        return output_class_ranks.tolist()