"""Strategy Vault — promoted strategies from the 10-strategy tournament (>300% return).

Champion (S07 + S03 + S02 + S08 consensus) plus individual promoted strategies.
"""
from typing import Callable, Dict
from .hypotheses import STRATEGIES

# Promoted strategies with >300% return on $10 bankroll over 7 days
PROMOTED: Dict[str, Callable] = {
    "S07_SPOT_TWAP_ACCELERATION": STRATEGIES["S07_SPOT_TWAP_ACCELERATION"],
    "S01_KEMNA_VORST_TWAP_BS": STRATEGIES["S01_KEMNA_VORST_TWAP_BS"],
    "S02_LOW_VOL_THETA_DECAY": STRATEGIES["S02_LOW_VOL_THETA_DECAY"],
    "S03_PRE_TWAP_LOCKIN_SNIPER": STRATEGIES["S03_PRE_TWAP_LOCKIN_SNIPER"],
    "S08_CLOB_BOOK_IMBALANCE_HYBRID": STRATEGIES["S08_CLOB_BOOK_IMBALANCE_HYBRID"],
    "S10_LOGIT_BAYESIAN_ENSEMBLE": STRATEGIES["S10_LOGIT_BAYESIAN_ENSEMBLE"],
}

# Rejected strategies
REJECTED = ["S04_CVD_DRIFT_BS", "S05_PASSIVE_ABSORPTION_BREAKOUT", "S06_EXHAUSTION_MEAN_REVERSION", "S09_REGIME_SWITCHING_ADAPTIVE"]