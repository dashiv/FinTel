"""
utils/llm.py
------------
All communication with your local Ollama AI goes through here.
No data leaves your machine. No API costs. Everything is local.
"""

import json, re
from tenacity import retry, stop_after_attempt, wait_exponential
from utils.logger import logger

try:
    from config.settings import (
        OLLAMA_CLASSIFICATION_MODEL,
        OLLAMA_ANALYSIS_MODEL,
        OLLAMA_BASE_URL,
    )
except ImportError:
    OLLAMA_CLASSIFICATION_MODEL = "mistral:7b"
    OLLAMA_ANALYSIS_MODEL       = "deepseek-r1:7b"
    OLLAMA_BASE_URL             = "http://localhost:11434"


def check_ollama_running() -> bool:
    """Returns True if Ollama is running on your machine."""
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_BASE_URL)
        client.list()
        return True
    except Exception:
        return False


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def ask_llm(prompt: str, model: str = None, temperature: float = 0.1) -> str:
    """
    Send a prompt to your local Ollama model, get a text response back.

    temperature: 0.0 = very focused and consistent (use for analysis)
                 0.7 = more creative (use for summaries)
    """
    import ollama
    if model is None:
        model = OLLAMA_CLASSIFICATION_MODEL

    client = ollama.Client(host=OLLAMA_BASE_URL)
    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": temperature},
    )
    return response["message"]["content"]


def ask_llm_for_json(prompt: str, model: str = None) -> dict:
    """
    Like ask_llm() but expects a JSON response.
    Returns a Python dictionary. Returns {} if parsing fails.
    """
    json_prompt = (
        prompt
        + "\n\nIMPORTANT: Respond ONLY with a valid JSON object. "
        "No explanation, no markdown code fences. Just the raw JSON."
    )
    raw = ask_llm(json_prompt, model=model, temperature=0.0)

    # Attempt 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract first {...} block
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        pass

    logger.warning(f"Could not parse JSON from LLM: {raw[:200]}")
    return {}


def classify_company_sector(
    company_name: str,
    description: str,
    available_sectors: list,
) -> dict:
    """
    Ask the AI to classify a company into one of your tracked sectors.

    Returns dict with:
        primary_sector, secondary_sector, confidence,
        reasoning, interest_score, score_rationale
    """
    sectors_str = ", ".join(available_sectors)

    prompt = f"""You are an expert equity analyst specialising in technology sector classification.

COMPANY: {company_name}

DESCRIPTION:
{description}

AVAILABLE SECTORS (choose only from this list):
{sectors_str}

Classify this company and respond with a JSON object containing:
- primary_sector   : best matching sector (or "other" if none fit)
- secondary_sector : second sector if relevant (or null)
- confidence       : 0.0 to 1.0 — how sure you are
- reasoning        : one sentence explaining your classification
- interest_score   : integer 0-100 for a growth investor
  (100=exceptional unique opportunity, 50=decent but crowded, 0=no growth angle)
- score_rationale  : one sentence explaining the interest score"""

    result = ask_llm_for_json(prompt)

    return {
        "primary_sector":   result.get("primary_sector", "other"),
        "secondary_sector": result.get("secondary_sector"),
        "confidence":       result.get("confidence", 0.5),
        "reasoning":        result.get("reasoning", ""),
        "interest_score":   result.get("interest_score", 50),
        "score_rationale":  result.get("score_rationale", ""),
    }


if __name__ == "__main__":
    print("Checking Ollama...")
    if check_ollama_running():
        print("✅ Ollama is running!")
        print("\nRunning a quick test classification...")
        r = classify_company_sector(
            company_name="QuantumLeap Inc.",
            description="We build superconducting quantum processors for drug discovery.",
            available_sectors=["quantum_computing", "pharma_biotech", "artificial_intelligence"],
        )
        print(json.dumps(r, indent=2))
    else:
        print("❌ Ollama is NOT running.")
        print("Fix: open a new Command Prompt and run:  ollama serve")

def generate_company_summary(filing: dict) -> str:
    """Return a concise AI-written investment summary for a filing.

    The prompt draws on company name, ticker, sector, interest score and
    filing date. Results are cached by caller if desired.
    """
    name = filing.get('company_name','')
    ticker = filing.get('ticker','<no ticker>')
    sector = filing.get('primary_sector','')
    score = filing.get('interest_score','?')
    date = filing.get('filing_date','')[:10]

    prompt = f"""You are a knowledgeable IPO analyst. Write a 2-3 sentence
investment summary for the following company, suitable for a busy investor.

Company: {name} ({ticker})
Primary sector: {sector}
Interest score: {score}
Filing date: {date}

Include strengths, potential risks, and any notable details. """

    # use a slightly higher temperature for creativity
    return ask_llm(prompt, model=OLLAMA_ANALYSIS_MODEL, temperature=0.3)