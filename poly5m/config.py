from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    # --- $10 Bankroll Sizing & Exposure ---
    starting_bankroll: float = 10.00
    base_shares_per_trade: float = 5.0       # Polymarket min order size = 5 shares
    max_usdc_per_trade: float = 3.00         # Supports 5 shares up to $0.60
    max_trades_per_window: int = 1           # Strictly 1 sniper entry per 5m window
    max_concurrent_windows: int = 1          # 1 active in-play window at a time
    max_total_exposure: float = 5.00         # Max 50% bankroll locked across settling windows

    # --- Entry Price Band & Edge Filters ---
    min_token_price: float = 0.44            # Avoid low-prob tail variance
    max_token_price: float = 0.62            # Includes $0.58 cohort test, caps R:R downside
    min_ev_edge: float = 0.055               # Must clear ~1.7c fee + ~0.5c slippage + 3.3c alpha
    max_book_spread: float = 0.025           # Max 2.5 cents bid-ask spread
    min_entry_elapsed_sec: int = 30          # Wait 30s after open
    max_entry_elapsed_sec: int = 210         # No entries in final 90s (TWAP lock-in / gamma zone)

    # --- Circuit Breakers & Kill Switches ---
    kill_switch_balance: float = 6.00        # Stop trading if bankroll hits $6.00 (-40% DD)
    max_consecutive_losses: int = 4          # Cooldown after 4 consecutive losses
    cooldown_windows_after_streak: int = 6   # Skip 30 mins (6 windows) after loss streak
    stale_data_kill_ms: int = 1000           # 1.0s max feed latency


@dataclass(frozen=True)
class ExecutionPhysicsConfig:
    # --- Polymarket Crypto Market Fee & Microstructure Rules ---
    fee_coeff: float = 0.07                  # C * 0.07 * p * (1 - p)
    min_fee_usdc: float = 0.00001            # Minimum fee floor
    tick_size: float = 0.001                 # 0.1 cent tick size
    min_order_size_shares: float = 5.0       # Minimum 5 shares per order
    depth_haircut: float = 0.50              # Assume only 50% of displayed book depth is fillable
    slippage_multiplier: float = 1.0         # 1.0x normal, 2.0x in stress test
    simulated_latency_ms: int = 150          # 150ms baseline execution latency
    fill_probability: float = 1.0            # 1.0 normal, 0.80 in stress test


@dataclass(frozen=True)
class BotConfig:
    dry_run: bool = True                     # HARD GUARD: Never send live orders when True
    risk: RiskConfig = RiskConfig()
    physics: ExecutionPhysicsConfig = ExecutionPhysicsConfig()
    data_dir: str = "data"