import json
import os
from openai import OpenAI

# API key setup
api_key_path = "scripts/api.json"
with open(api_key_path, 'r') as f:
    api_key = json.load(f).get('Knovel', 0)

client = OpenAI(api_key=api_key)
MODEL = "gpt-4o-mini"



# Old experiment
data_file_path = 'OmniMod/Results/abnormal/20250106160/result/abnormal_explainable_test_checkpoint_6_rearranged_file.json'
output_file_path = 'OmniMod/Results/abnormal/20250106160/result/reasoning_result_gpt4_new_criteria.json'

# data_file_path = 'OmniMod/Results/abnormal_new/20250115151/result/Abnormal_test_checkpoint_9_rearranged_file.json'
# output_file_path = "OmniMod/Results/abnormal_new/20250115151/result/test_reasoning_result_gpt4_new_criteria.json"
# Input and output paths
# data_file_path = "OmniMod/Results/abnormal_new/20250115151/result/Abnormal_train_checkpoint_rearranged_file.json"
# output_file_path = "OmniMod/Results/abnormal_new/20250115151/result/train_reasoning_result_gpt4.json"


# abnormal_OmniMedVQA_checkpoint_19 llama 3.1
# data_file_path = "OmniMod/Results/abnormal_OmniMedVQA_llama31/20250208160/result/abnormal_OmniMedVQA_checkpoint_19_rearranged_file.json"
# output_file_path = "OmniMod/Results/abnormal_OmniMedVQA_llama31/20250208160/result/reasoning_result_gpt4_t3.json"


# # abnormal_OmniMedVQA_checkpoint_19 deepseek
# data_file_path = "OmniMod/Results/abnormal_OmniMedVQA_deepseek/20250208160/result/abnormal_OmniMedVQA_checkpoint_19_rearranged_file.json"
# output_file_path = "OmniMod/Results/abnormal_OmniMedVQA_deepseek/20250208160/result/reasoning_result_gpt4_t3.json"


# Ablation study cot, tot
# data_file_path = "OmniMod/Results/ablation_study_llama31_cot/20250209132/result/Ablation_study_checkpoint_19_rearranged_file.json"
# output_file_path = "OmniMod/Results/ablation_study_llama31_cot/20250209132/result/reasoning_result_gpt4_cot.json"

# data_file_path = "OmniMod/Results/ablation_study_llama31_tot/20250209141/result/Ablation_study_checkpoint_19_rearranged_file.json"
# output_file_path = "OmniMod/Results/ablation_study_llama31_tot/20250209141/result/reasoning_result_gpt4_tot.json"


# # Abnormal deepseek old
# data_file_path = "OmniMod/Results/abnormal_combine_deepseek/20250210112/result/Abnormal_checkpoint_49_rearranged_file.json"
# output_file_path = "OmniMod/Results/abnormal_combine_deepseek/20250210112/result/reasoning_result_gpt4_new_criteria.json"



# Prompt for evaluation
evaluation_prompt = '''
Task: 

You are given a question, a ground truth, and a prediction in medical analysis. Evaluate the text-based model prediction for its relevance, accuracy, and alignment with the ground truth. 

Scoring: Assign a score from 0 to 3 based on the following criteria:

    0: Completely Incorrect: The prediction does not answer the question, is off-topic, or is entirely unrelated to the ground truth.
    1: Significantly Incorrect: The prediction attempts to answer the question but does not match the ground truth in terms of understanding, terminology, or core explanation.
    2: Partially Incorrect: The prediction directly answers the question and provides an explanation. Both the answer and the explanation reflect a reasonable understanding of the main idea, though they contain minor irrelevant or incorrect information.
    3: Fully Correct: The prediction completely aligns with the ground truth, providing both a clear answer and a well-reasoned explanation.

Output structure:
{
    "evaluation": Provide a concise justification sentence explaining why you rated the score.
    "score": score
}
'''

# Load the input data
with open(data_file_path, "r") as f:
    input_data = json.load(f)

# Initialize or load existing JSON output
if os.path.exists(output_file_path):
    with open(output_file_path, "r") as infile:
        output_data = json.load(infile)
else:
    output_data = []

# Process each entry in the dataset
for i, entry in enumerate(input_data):
      try:
            # Prepare the message for the model
            messages = [
                  {"role": "system", "content": "You are a helpful assistant that evaluates predictions in medical analysis."},
                  {"role": "user", "content": [
                  {"type": "text", "text":
                  f"Question: {entry['text_question']}\
                    Ground Truth: {entry['ground_truth']}\
                    Prediction: {entry['predict']}\
                    Evaluation metrics: {evaluation_prompt}"}
            ]}]

            # Get response from the model
            response = client.chat.completions.create(
                  model=MODEL,
                  messages=messages,
                  temperature=0.1
            )

            # Parse the response
            response_text = response.choices[0].message.content
            evaluation_result = json.loads(response_text)

            # Append results to output data
            output_entry = {
                  "image_id": entry["image_id"],
                  "text_question": entry["text_question"],
                  "ground_truth": entry["ground_truth"],
                  "predict": entry["predict"],
                  "evaluation": evaluation_result
            }
            output_data.append(output_entry)

            print(f"Processed entry {i+1}/{len(input_data)}: {entry['image_id']}")

      except Exception as e:
            print(f"Error processing entry {i+1}/{len(input_data)}: {entry['image_id']}: {e}")
            
    #   if i ==1: break

# Save results to the output JSON file
with open(output_file_path, "w") as outfile:
    json.dump(output_data, outfile, indent=4)

print(f"Evaluation completed. Results saved to {output_file_path}")
