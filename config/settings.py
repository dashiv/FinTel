# ============================================================
# FinTel Settings
# This is YOUR personal config file. Never share this file.
# ============================================================

# --- AI Models (Ollama runs locally - free) ---
OLLAMA_CLASSIFICATION_MODEL = "mistral:7b"
OLLAMA_ANALYSIS_MODEL = "deepseek-r1:7b"
OLLAMA_BASE_URL = "http://localhost:11434"

# --- Database ---
DB_PATH = "fintel.db"

# --- IPO Scout ---
IPO_LOOKBACK_DAYS = 30
IPO_MIN_SCORE_THRESHOLD = 55

# --- Sectors to track ---
TRACKED_SECTORS = [
    "artificial_intelligence",
    "quantum_computing",
    "semiconductors_gan",
    "drone_aviation",
    "pharma_biotech",
    "defense_tech",
    "clean_energy",
    "cybersecurity",
    "space_tech",
    "fintech",
]

# --- Signal scoring weights (must add to 100) ---
SCORE_WEIGHT_TECHNICAL    = 30
SCORE_WEIGHT_SENTIMENT    = 30
SCORE_WEIGHT_SECTOR       = 25
SCORE_WEIGHT_FUNDAMENTALS = 15

# --- Luxembourg tax optimisation ---
LUX_TAX_FREE_HOLD_DAYS = 183
PREFER_TAX_FREE_HOLDS  = True

# --- Your capital ---
# TODO: Update this to your actual available trading capital in EUR
TOTAL_CAPITAL_EUR = 5000

# --- Risk rules ---
MAX_POSITION_PCT             = 0.20   # max 20% of capital per stock
MAX_OPEN_POSITIONS           = 5
MAX_SECTOR_CONCENTRATION_PCT = 0.40

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FILE  = "logs/fintel.log"
