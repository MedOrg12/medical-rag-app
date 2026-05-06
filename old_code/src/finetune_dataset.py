"""
Fine-tuning dataset generator for medical research models.
Creates question-answer pairs from parsed PDFs for model fine-tuning.
"""

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import settings
from src.logger import logger
from src.pdf_parser import PDFDocument


@dataclass
class TrainingExample:
    """Training example for fine-tuning."""

    prompt: str
    response: str
    metadata: dict[str, Any]


class FineTuneDatasetGenerator:
    """
    Generate fine-tuning datasets from medical research PDFs.
    Creates synthetic Q&A pairs based on document content.
    """

    def __init__(self, output_dir: Path = None):
        """
        Initialize the dataset generator.

        Args:
            output_dir: Directory to save generated datasets
        """
        self.output_dir = output_dir or settings.data_folder
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_key_findings(self, section: dict[str, Any]) -> list[str]:
        """
        Extract key findings from a section.

        Args:
            section: Section dictionary with title and content

        Returns:
            List of potential findings
        """
        content = section.get("content", "")
        findings = []

        # Look for common patterns in medical research
        patterns = [
            r"(?:we found|results showed|demonstrated|observed|revealed)\s+that\s+([^.]+\.)",
            r"(?:significant|significantly)\s+([^.]+\.)",
            r"(?:conclusion:|conclusions:)\s*([^.]+\.)",
            r"(?:p\s*[<>=]\s*0\.\d+)\s+([^.]+\.)",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                finding = match.group(0).strip()
                if len(finding) > 20 and len(finding) < 500:
                    findings.append(finding)

        return findings

    def generate_section_qa(
        self, section: dict[str, Any], doc: PDFDocument
    ) -> list[TrainingExample]:
        """
        Generate Q&A pairs from a document section.

        Args:
            section: Section dictionary
            doc: Parent PDFDocument

        Returns:
            List of TrainingExample objects
        """
        examples = []
        section_title = section.get("title", "").lower()
        content = section.get("content", "")

        if not content.strip():
            return []

        # Template-based Q&A generation
        templates = []

        # Abstract/Introduction questions
        if "abstract" in section_title or "introduction" in section_title:
            templates.extend(
                [
                    {
                        "prompt": f"What is the main objective of the study in {doc.title}?",
                        "response_template": f"Based on {doc.title}, {content[:500]}...",
                    },
                    {
                        "prompt": f"What is the background and motivation for {doc.title}?",
                        "response_template": f"The study background from {doc.title}: {content[:500]}...",
                    },
                ]
            )

        # Methods questions
        elif "method" in section_title or "material" in section_title:
            templates.extend(
                [
                    {
                        "prompt": f"What methodology was used in {doc.title}?",
                        "response_template": f"The methodology in {doc.title} includes: {content[:500]}...",
                    },
                    {
                        "prompt": f"Describe the research design of {doc.title}.",
                        "response_template": f"The research design from {doc.title}: {content[:500]}...",
                    },
                ]
            )

        # Results questions
        elif "result" in section_title:
            templates.extend(
                [
                    {
                        "prompt": f"What were the main findings in {doc.title}?",
                        "response_template": f"The main findings from {doc.title} were: {content[:500]}...",
                    },
                    {
                        "prompt": f"Summarize the results of {doc.title}.",
                        "response_template": f"Results summary from {doc.title}: {content[:500]}...",
                    },
                ]
            )

            # Extract key findings
            findings = self.extract_key_findings(section)
            for finding in findings[:3]:  # Limit to 3 findings per section
                templates.append(
                    {
                        "prompt": f"What did {doc.title} find regarding {finding[:50]}?",
                        "response_template": f"According to {doc.title}: {finding}",
                    }
                )

        # Discussion/Conclusion questions
        elif "discussion" in section_title or "conclusion" in section_title:
            templates.extend(
                [
                    {
                        "prompt": f"What are the conclusions of {doc.title}?",
                        "response_template": f"The conclusions from {doc.title}: {content[:500]}...",
                    },
                    {
                        "prompt": f"What are the implications of {doc.title}?",
                        "response_template": f"The implications discussed in {doc.title}: {content[:500]}...",
                    },
                ]
            )

        # Create training examples from templates
        for template in templates:
            # Extract a meaningful response from content
            response = self._create_response(content, template.get("response_template", ""), doc)

            if response:
                example = TrainingExample(
                    prompt=template["prompt"],
                    response=response,
                    metadata={
                        "source_file": doc.file_name,
                        "source_title": doc.title,
                        "section": section_title,
                    },
                )
                examples.append(example)

        return examples

    def _create_response(
        self, content: str, template: str, doc: PDFDocument, max_length: int = 500
    ) -> str:
        """
        Create a response from content using template.

        Args:
            content: Section content
            template: Response template
            doc: Document metadata
            max_length: Maximum response length

        Returns:
            Formatted response
        """
        # Clean content
        content = re.sub(r"\[Page \d+\]\n?", "", content)
        content = " ".join(content.split())  # Normalize whitespace

        # Take first meaningful portion
        sentences = content.split(". ")
        response_parts = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_length = len(sentence)
            if current_length + sentence_length > max_length:
                break

            response_parts.append(sentence)
            current_length += sentence_length

        if not response_parts:
            return ""

        response_text = ". ".join(response_parts)
        if not response_text.endswith("."):
            response_text += "."

        # Add source citation
        response = f"{response_text}\n\n" f"[Source: {doc.file_name}]"

        return response

    def generate_dataset(
        self, documents: list[PDFDocument], min_examples: int = 10, max_examples_per_doc: int = 20
    ) -> list[TrainingExample]:
        """
        Generate fine-tuning dataset from documents.

        Args:
            documents: List of PDFDocument objects
            min_examples: Minimum number of examples to generate
            max_examples_per_doc: Maximum examples per document

        Returns:
            List of TrainingExample objects
        """
        all_examples = []

        logger.info(f"Generating fine-tuning dataset from {len(documents)} documents")

        for doc in documents:
            doc_examples = []

            for section in doc.sections:
                section_examples = self.generate_section_qa(section, doc)
                doc_examples.extend(section_examples)

            # Limit examples per document
            if len(doc_examples) > max_examples_per_doc:
                doc_examples = random.sample(doc_examples, max_examples_per_doc)

            all_examples.extend(doc_examples)
            logger.info(f"Generated {len(doc_examples)} examples from {doc.file_name}")

        logger.info(f"Total examples generated: {len(all_examples)}")

        # Ensure minimum examples
        if len(all_examples) < min_examples:
            logger.warning(
                f"Generated only {len(all_examples)} examples, "
                f"which is less than minimum {min_examples}"
            )

        return all_examples

    def save_dataset(
        self,
        examples: list[TrainingExample],
        filename: str = "finetune_dataset.jsonl",
        format_type: str = "alpaca",
    ) -> Path:
        """
        Save dataset to file.

        Args:
            examples: List of TrainingExample objects
            filename: Output filename
            format_type: Dataset format (alpaca, chatml, plain)

        Returns:
            Path to saved file
        """
        output_path = self.output_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            for example in examples:
                if format_type == "alpaca":
                    # Alpaca format
                    entry = {"instruction": example.prompt, "input": "", "output": example.response}
                elif format_type == "chatml":
                    # ChatML format
                    entry = {
                        "messages": [
                            {"role": "user", "content": example.prompt},
                            {"role": "assistant", "content": example.response},
                        ]
                    }
                else:  # plain
                    # Simple prompt/response format
                    entry = {"prompt": example.prompt, "response": example.response}

                # Add metadata
                entry["metadata"] = example.metadata

                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(f"Saved {len(examples)} examples to {output_path}")
        return output_path

    def create_unsloth_instructions(self, dataset_path: Path) -> str:
        """
        Create instructions for fine-tuning with Unsloth.

        Args:
            dataset_path: Path to the dataset file

        Returns:
            Instructions as string
        """
        instructions = f"""
# Fine-tuning Instructions using Unsloth

## Prerequisites
1. Install Unsloth and dependencies:
   ```bash
   pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
   pip install torch transformers datasets peft accelerate
   ```

## Fine-tuning Script

```python
from unsloth import FastLanguageModel
from datasets import load_dataset
import torch

# Load model
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/mistral-7b-bnb-4bit",  # or another base model
    max_seq_length=2048,
    dtype=None,
    load_in_4bit=True,
)

# Add LoRA adapters
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing=True,
    random_state=3407,
)

# Load dataset
dataset = load_dataset("json", data_files="{dataset_path}")

# Format prompts
def format_prompts(examples):
    texts = []
    for instruction, response in zip(examples["instruction"], examples["output"]):
        text = f'''Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
{{instruction}}

### Response:
{{response}}'''
        texts.append(text)
    return {{"text": texts}}

dataset = dataset.map(format_prompts, batched=True)

# Training
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset["train"],
    dataset_text_field="text",
    max_seq_length=2048,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=100,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=1,
        output_dir="outputs",
        optim="adamw_8bit",
    ),
)

trainer.train()

# Save model
model.save_pretrained("medical_research_model")
tokenizer.save_pretrained("medical_research_model")
```

## Export to Ollama

After training, export to GGUF and import to Ollama:

```python
# Export to GGUF
model.save_pretrained_gguf("medical_model", tokenizer, quantization_method="q4_k_m")
```

Then import to Ollama:
```bash
# Create Modelfile
cat > MedicalModelfile << EOF
FROM ./medical_model/medical_model-q4_k_m.gguf
SYSTEM "You are a medical research assistant trained on clinical literature."
EOF

# Create Ollama model
ollama create medical-research-ft -f MedicalModelfile
```

## Dataset Info
- Dataset path: {dataset_path}
- Format: Alpaca (instruction, input, output)
- Use for medical research Q&A fine-tuning
"""

        return instructions


if __name__ == "__main__":
    from src.pdf_parser import PDFParser

    # Parse PDFs
    parser = PDFParser()
    docs = parser.parse_all(save_json=False)

    if docs:
        # Generate dataset
        generator = FineTuneDatasetGenerator()
        examples = generator.generate_dataset(docs)

        if examples:
            # Save in multiple formats
            alpaca_path = generator.save_dataset(examples, "finetune_alpaca.jsonl", "alpaca")
            chatml_path = generator.save_dataset(examples, "finetune_chatml.jsonl", "chatml")

            # Create instructions
            instructions = generator.create_unsloth_instructions(alpaca_path)
            instructions_path = generator.output_dir / "FINETUNING_INSTRUCTIONS.md"

            with open(instructions_path, "w") as f:
                f.write(instructions)

            print(f"\nGenerated {len(examples)} training examples")
            print("Saved to:")
            print(f"  - {alpaca_path}")
            print(f"  - {chatml_path}")
            print(f"  - {instructions_path}")
        else:
            print("No examples generated. Check if PDFs have content.")
    else:
        print("No documents parsed. Add PDFs to ./pdf folder.")
