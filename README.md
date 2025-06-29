# SilVar-Med: A Speech-Driven Visual Language Model for Explainable Abnormality Detection in Medical Imaging

<div style="text-align: center;">
  <img src="images/images_architecture.png" alt="Speech-Driven Medical VLM" width="800"/>
  <p><i>SilVar-Med enables speech-based interaction with medical VLMs for abnormality detection and explanation.</i></p>
</div>

---

## Overview and Contribution

**SilVar-Med** introduces the first **speech-driven multimodal visual language model** tailored for medical imaging. This project pioneers **voice-based interaction** with medical VLMs, enabling clinicians to **ask questions verbally** and receive **interpretable answers** with reasoning behind each medical abnormality prediction.

We tackle two key challenges:
- Making VLMs operable via **speech** in clinical settings.
- Providing **transparent, explainable predictions** to improve trust in AI-assisted diagnosis.

Our model integrates:
- A medical vision encoder: CLIP and its variants
- A speech encoder: Whispers
- A language model: Mistral, Llama (2, 3, 3.1), Deepseek R1 (Distill Llama 8B) 
- And a reasoning-aware fusion mechanism.

Pretrained weights and datasets:
- We released our checkpoint for SilvarMed [here](https://drive.google.com/file/d/1e7qGgr-AReFI7H9uSofmRZjMtXuD_tYq/view?usp=sharing).
- Dataset [here](https://huggingface.co/datasets/Hanhpt23/Silvar-Med)
---


## Installation

```bash
conda create -n SilVarMed python=3.10.13
conda activate SilVarMed
git clone https://github.com/Hanhpt23/SilVarMed.git
cd SilVarMed
pip install -r requirements.txt
```

## Training Section

**Training Configuration:**

- **Model:**
  - Vision Model: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L7) at Line 7
  - Audio Model: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L8) at Line 8
  - Language Model: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L9) at Line 9
  - Others: `lora_r`, `freeze_vision`, `freeze_audio`
    - If you want to train the model end-to-end, set `freeze_vision` and `freeze_audio` to `False` [here](train_configs/train.yaml#L17) on lines 17 and 18

- **Datasets:**
  - Batch Size: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L22) at Line 22
  - Image Path: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L35) at Line 35
  - Annotation Path: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L36) at Line 36
  - Audio Path: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L37) at Line 37

- **Run:**
  - Max Epoch: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L47) at Line 47
  - Iterations per Epoch: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L50) at Line 50
  - Output Directory: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L53) at Line 53
  - Weights and Biases Token: [here](train_configs/train_abnormal_OmniMedVQA_llama3.1.yaml#L67) at Line 67

**Testing Configuration:**

- **Model:**
  - Vision Model: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L7) at Line 7
  - Audio Model: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L8) at Line 8
  - Language Model: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L9) at Line 9
  - Checkpoint: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L10) at Line 10

- **Evaluation Datasets:**
  - Evaluation File Path:
  - Batch Size: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L39) at Line 39
  - Image Path: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L36) at Line 36
  - Audio Path: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L38) at Line 38

- **Run:**
  - Save Path: [here](eval_configs/eval_abnormal_OmniMedVQA_llama3.1.yaml#L47) at Line 47


```bash
torchrun --nproc_per_node 1 train.py \
      --cfg-path train_configs/train_abnormal.yaml\
      --cfg-eval-path eval_configs/eval_abnormal.yaml\
      --eval-dataset audio_val
```


## Evaluation
```bash
torchrun --nproc_per_node 2 --master_port=29501 evaluate.py \
      --cfg-path eval_configs/eval_abnormal_one_train.yaml\
      --eval-dataset audio_val
```


## Dataset

<div style="text-align: center;">
  <img src="images/dataset.png" alt="Dataset Image" width="400"/>
  <p><i>Dataset labelling with medical image analysis specialist.</i></p>
</div>



---

## Experiments and Results

<div style="text-align: center;">
  <img src="images/results.png" alt="Comparison of SilVar-Med with various text-based medical VLMs on the SLAKE and VQA-RAD datasets. Results are reported for both open-ended and closed-ended questions, with reference-based scores where applicable." width="800"/>
  <p><i>Comparison of SilVar-Med with various text-based medical VLMs on the SLAKE and VQA-RAD datasets. Results are reported for both open-ended and closed-ended questions, with reference-based scores where applicable.</i></p>
</div>

<div style="text-align: center;">
  <img src="images/prediction.png" alt="Comparison of prediction between our models and the other speech-driven model on the reasoning abnormal detection. Unlike GPT-4o and Gemini 1.5 Flash, our SilVar-Med is an end-to-end speech-driven VLM. For more demonstration, please visit." width="800"/>
  <p><i>Comparison of prediction between our models and other speech-driven models on reasoning abnormal detection. Unlike GPT-4o and Gemini 1.5 Flash, our SilVar-Med is an end-to-end speech-driven VLM. For more demonstrations, please visit <a href="https://github.com/Hanhpt23/SilVarMed">our repository</a>.</i></p>
</div>

## Citation

```bibtex
@InProceedings{Pham_2025_CVPR,
    author    = {Pham, Tan-Hanh and Bui, Trong-Duong and Quang, Minh Luu and Pham, Tan Huong and Ngo, Chris and Hy, Truong Son},
    title     = {SilVar-Med: A Speech-Driven Visual Language Model for Explainable Abnormality Detection in Medical Imaging},
    booktitle = {Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR) Workshops},
    month     = {June},
    year      = {2025},
    pages     = {2984-2994}
}
```