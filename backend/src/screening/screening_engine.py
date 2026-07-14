"""Four-layer funnel screening engine.

Pipeline: ~200 ETFs → Layer 1 (basic filter) → ~80 → Layer 2 (multi-factor) → ~30
       → Layer 3 (theme cluster) → ~10 → Layer 4 (risk filter) → 1-2 final picks
"""

from datetime import datetime
from typing import Optional
import numpy as np

from src.domain.entities import ETF, ScreeningResult, FactorScore
from src.indicators.technical import IndicatorCalculator
from src.infrastructure.data_provider_factory import get_data_provider
from config import settings


class ScreeningEngine:
    """Orchestrates the four-layer screening pipeline."""

    def __init__(self, data_provider=None):
        self.mock = data_provider or get_data_provider()
        self._pipeline_counts: dict = {}  # track counts per layer

    def run_full_screening(self, select_date: Optional[str] = None) -> list[ScreeningResult]:
        """Run the complete four-layer screening pipeline.

        Returns list of ScreeningResult for all ETFs that passed layer 1,
        with final_recommended=True for the 1-2 final picks.
        """
        if select_date is None:
            select_date = datetime.now().strftime("%Y-%m-%d")

        # Get all ETFs from pool
        all_etfs = self.mock.get_etf_pool()
        print(f"[Screening] Layer 0: {len(all_etfs)} ETFs in pool")
        self._pipeline_counts = {"pool_total": len(all_etfs)}

        # === Layer 1: Basic Filter ===
        layer1_results = self._layer1_basic_filter(all_etfs, select_date)
        self._pipeline_counts["layer1"] = len(layer1_results)
        print(f"[Screening] Layer 1 (basic filter): {len(layer1_results)} ETFs passed")

        # === Layer 2: Multi-Factor Scoring ===
        layer2_results = self._layer2_multi_factor_scoring(layer1_results, select_date)
        top30 = layer2_results[:30]
        self._pipeline_counts["layer2"] = min(len(layer2_results), 30)
        print(f"[Screening] Layer 2 (multi-factor): {len(layer2_results)} scored, top 30 selected")

        # === Layer 3: Theme Clustering ===
        layer3_results = self._layer3_theme_clustering(top30, select_date)
        self._pipeline_counts["layer3"] = len(layer3_results)
        print(f"[Screening] Layer 3 (theme cluster): {len(layer3_results)} ETFs after clustering")

        # === Layer 4: Deep Risk Filter ===
        layer4_results = self._layer4_risk_filter(layer3_results, select_date)
        recommended = [r for r in layer4_results if r.layer4_passed]
        self._pipeline_counts["layer4"] = len(recommended)
        print(f"[Screening] Layer 4 (risk filter): {len(layer4_results)} checked, {len(recommended)} recommended")

        # Mark final recommendations (max 2)
        for r in layer4_results:
            r.final_recommended = r.layer4_passed
        final_picks = [r for r in layer4_results if r.final_recommended][:settings.DAILY_SELECT_COUNT]

        # Only mark the top picks as recommended
        for r in layer4_results:
            r.final_recommended = False
        for r in final_picks:
            r.final_recommended = True

        self._pipeline_counts["final"] = len(final_picks)
        print(f"[Screening] Final recommendations: {len(final_picks)} ETFs")
        return layer4_results

    def _layer1_basic_filter(self, etfs: list[ETF], select_date: str) -> list[ScreeningResult]:
        """Layer 1: Basic filter - exclude low liquidity, small cap, bond/currency/LOF, new listings."""
        results: list[ScreeningResult] = []
        liquidity_min = settings.LIQUIDITY_THRESHOLD    # 3000万元
        cap_min = settings.MARKET_CAP_THRESHOLD          # 80亿元

        for etf in etfs:
            result = ScreeningResult(
                etf_code=etf.code,
                etf_name=etf.name,
                select_date=select_date,
            )

            # Skip blacklisted
            if etf.status == "blacklist":
                continue

            # Whitelist always passes
            if etf.status == "whitelist":
                result.layer1_passed = True
                results.append(result)
                continue

            # Exclude bond, monetary, LOF types
            if etf.theme in ("债券/货币/LOF",):
                continue

            # Exclude excluded status
            if etf.status == "excluded":
                continue

            # Exclude if data abnormal
            if etf.data_status != "normal":
                continue

            # Liquidity check: avg 20-day amount >= 3000万
            if etf.avg_amount_20d < liquidity_min:
                continue

            # Market cap check: >= 80亿
            if etf.total_market_cap < cap_min:
                continue

            # Listing age check: at least 20 trading days
            if etf.list_date:
                list_dt = datetime.strptime(etf.list_date, "%Y-%m-%d")
                days_since = (datetime.now() - list_dt).days
                if days_since < 30:  # Approximate 20 trading days
                    continue

            result.layer1_passed = True
            results.append(result)

        return results

    def _layer2_multi_factor_scoring(self, results: list[ScreeningResult],
                                       select_date: str) -> list[ScreeningResult]:
        """Layer 2: Multi-factor scoring with Z-Score standardization.

        Factors: trend strength (25%), momentum (20%), volume (15%),
                 volatility (10%), technical indicators (30%)
        """
        # Calculate raw factor values for all ETFs
        factor_data: list[dict] = []
        for result in results:
            etf = self._get_etf(result.etf_code)
            if not etf:
                continue
            klines = self.mock.get_klines(result.etf_code, 120)
            if len(klines) < 30:
                continue

            calc = IndicatorCalculator(klines)
            indicators = calc.get_all_indicators()
            if not indicators:
                continue

            # Compute 8 technical sub-scores
            tech_scores = self._compute_technical_subscores(indicators)

            factor_data.append({
                "result": result,
                "etf": etf,
                "indicators": indicators,
                "tech_scores": tech_scores,
                # Raw values
                "trend_slope": indicators["trend_slope"],
                "momentum": indicators["momentum"],
                "volume_ratio": indicators["volume_ratio"],
                "volatility": indicators["annualized_volatility"],
                "technical_score": np.mean(tech_scores) if tech_scores else 0,
            })

        if not factor_data:
            return results

        # Z-Score standardization for each factor
        for factor_name in ["trend_slope", "momentum", "volume_ratio", "volatility", "technical_score"]:
            values = [d[factor_name] for d in factor_data]
            mean = np.mean(values)
            std = np.std(values)
            if std == 0:
                std = 1
            for d in factor_data:
                d[f"{factor_name}_z"] = (d[factor_name] - mean) / std

        # Compute composite score
        for d in factor_data:
            # For volatility, lower is better, so invert Z-score
            vol_z = -d["volatility_z"]
            composite = (
                d["trend_slope_z"] * settings.WEIGHT_TREND +
                d["momentum_z"] * settings.WEIGHT_MOMENTUM +
                d["volume_ratio_z"] * settings.WEIGHT_VOLUME +
                vol_z * settings.WEIGHT_VOLATILITY +
                d["technical_score_z"] * settings.WEIGHT_TECHNICAL
            )
            d["composite_score"] = float(composite)

            # Store factor scores
            d["result"].factor_scores = [
                FactorScore("趋势强度", round(d["trend_slope"], 6), round(d["trend_slope_z"], 4), settings.WEIGHT_TREND),
                FactorScore("动量得分", round(d["momentum"], 4), round(d["momentum_z"], 4), settings.WEIGHT_MOMENTUM),
                FactorScore("量能指标", round(d["volume_ratio"], 4), round(d["volume_ratio_z"], 4), settings.WEIGHT_VOLUME),
                FactorScore("波动率", round(d["volatility"], 4), round(vol_z, 4), settings.WEIGHT_VOLATILITY),
                FactorScore("技术指标", round(d["technical_score"], 4), round(d["technical_score_z"], 4), settings.WEIGHT_TECHNICAL),
            ]
            d["result"].layer2_score = round(d["composite_score"], 4)

        # Sort by composite score descending
        factor_data.sort(key=lambda x: x["composite_score"], reverse=True)

        # Assign ranks and pick top 30
        for rank, d in enumerate(factor_data, 1):
            d["result"].layer2_rank = rank

        return [d["result"] for d in factor_data]

    def _compute_technical_subscores(self, indicators: dict) -> list[float]:
        """Compute 8 technical sub-scores for the 'other technical indicators' factor.

        Each sub-score is in range [-1, 1] where positive = bullish.
        """
        scores = []

        # 1. RSI (14-day): 30-70 normal, <30 oversold (bullish), >70 overbought (bearish)
        rsi = indicators.get("RSI")
        if rsi is not None and not np.isnan(rsi):
            if rsi < 30:
                scores.append(1.0)  # Oversold, expect bounce
            elif rsi > 70:
                scores.append(-1.0)  # Overbought
            else:
                scores.append((70 - rsi) / 40)  # Linear scale
        else:
            scores.append(0.0)

        # 2. MACD Golden/Death Cross
        macd = indicators.get("MACD", {})
        if macd.get("is_golden_cross"):
            scores.append(1.0)
        elif macd.get("line") is not None and macd.get("signal") is not None:
            if macd["line"] < macd["signal"]:
                scores.append(-0.5)
            else:
                scores.append(0.3)
        else:
            scores.append(0.0)

        # 3. MACD Histogram
        hist = macd.get("hist")
        if hist is not None and not np.isnan(hist):
            scores.append(1.0 if hist > 0 else -1.0)
        else:
            scores.append(0.0)

        # 4. KDJ-J value
        j = indicators.get("KDJ_J")
        if j is not None:
            if j < 20:
                scores.append(1.0)  # Oversold
            elif j > 80:
                scores.append(-1.0)  # Overbought
            else:
                scores.append((80 - j) / 60)
        else:
            scores.append(0.0)

        # 5. OBV direction
        obv_dir = indicators.get("OBV_direction", 0)
        scores.append(float(obv_dir))

        # 6. Bollinger Band position
        bb = indicators.get("BB", {})
        pos = bb.get("position")
        if pos is not None:
            # Near lower band (pos ~0) = bullish, near upper (pos ~1) = bearish
            scores.append(0.5 - pos)
        else:
            scores.append(0.0)

        # 7. BIAS (deviation from MA20)
        bias = indicators.get("BIAS")
        if bias is not None:
            # Negative bias = oversold (bullish), positive = overbought (bearish)
            scores.append(-np.clip(bias / 5, -1, 1))
        else:
            scores.append(0.0)

        # 8. VR (Volume Ratio)
        vr = indicators.get("VR")
        if vr is not None:
            if vr > 1.2:
                scores.append(1.0)  # Capital inflow
            elif vr < 0.8:
                scores.append(-1.0)  # Capital outflow
            else:
                scores.append((vr - 1.0) / 0.2)  # Linear around 1.0
        else:
            scores.append(0.0)

        return scores

    def _layer3_theme_clustering(self, results: list[ScreeningResult],
                                  select_date: str) -> list[ScreeningResult]:
        """Layer 3: Theme clustering - keep top 2 per theme by daily change."""
        # Group by theme
        theme_groups: dict[str, list[ScreeningResult]] = {}
        for result in results:
            etf = self._get_etf(result.etf_code)
            if not etf:
                continue
            theme = etf.theme or "未分类"
            result.layer3_theme = theme
            if theme not in theme_groups:
                theme_groups[theme] = []
            theme_groups[theme].append(result)

        # For each theme, sort by daily change pct and keep top 2
        output: list[ScreeningResult] = []
        for theme, group in theme_groups.items():
            # Get daily change for sorting
            for r in group:
                klines = self.mock.get_klines(r.etf_code, 2)
                if len(klines) >= 2:
                    change = (klines[-1].close / klines[-2].close - 1) * 100
                    r.layer3_theme_rank = int(change * 100)  # temporary store
                else:
                    r.layer3_theme_rank = 0

            # Sort by change descending
            group.sort(key=lambda x: x.layer3_theme_rank, reverse=True)

            # Keep top 2
            for i, r in enumerate(group[:2]):
                r.layer3_theme_rank = i + 1
                r.layer3_passed = True
                output.append(r)

        return output

    def _layer4_risk_filter(self, results: list[ScreeningResult],
                            select_date: str) -> list[ScreeningResult]:
        """Layer 4: Deep risk filter - 4 risk checks, all must pass."""
        for result in results:
            etf = self._get_etf(result.etf_code)
            if not etf:
                continue
            klines = self.mock.get_klines(result.etf_code, 120)
            if len(klines) < 60:
                result.layer4_passed = False
                continue

            calc = IndicatorCalculator(klines)
            indicators = calc.get_all_indicators()

            # 1. Five-fold death cross detection
            result.layer4_death_cross = indicators.get("death_cross", False)

            # 2. Volume-price divergence detection
            result.layer4_vol_price_div = indicators.get("volume_price_divergence", False)

            # 3. ADX danger signal
            result.layer4_adx_danger = indicators.get("adx_danger", False)

            # 4. Bollinger band breakout risk
            result.layer4_bb_risk = indicators.get("bollinger_breakout", False)

            # All 4 checks must pass (all False = no risk detected)
            result.layer4_passed = not any([
                result.layer4_death_cross,
                result.layer4_vol_price_div,
                result.layer4_adx_danger,
                result.layer4_bb_risk,
            ])

        return results

    def _get_etf(self, code: str) -> Optional[ETF]:
        """Get ETF by code from pool."""
        for etf in self.mock.get_etf_pool():
            if etf.code == code:
                return etf
        return None

    def get_today_recommendations(self) -> list[ScreeningResult]:
        """Get today's recommended ETFs (final picks from screening)."""
        results = self.run_full_screening()
        return [r for r in results if r.final_recommended]

    def check_market_empty_signal(self) -> tuple[bool, str]:
        """Check if market condition triggers empty signal (空仓信号).

        Returns (is_empty, reason).
        """
        hs300_change = self.mock.get_hs300_today_change()
        if hs300_change < settings.MARKET_DROP_THRESHOLD:
            return True, f"沪深300当日跌幅{hs300_change:.2f}%超过阈值{settings.MARKET_DROP_THRESHOLD}%，建议观望"
        return False, ""

    def get_screening_summary(self, results: list[ScreeningResult]) -> dict:
        """Get a summary dict of the screening results for display."""
        funnel = self._pipeline_counts if self._pipeline_counts else {
            "pool_total": len(self.mock.get_etf_pool()),
            "layer1": 0, "layer2": 0, "layer3": 0, "layer4": 0, "final": 0,
        }

        return {
            "select_date": results[0].select_date if results else "",
            "layer1_passed": funnel.get("layer1", 0),
            "layer2_scored": funnel.get("layer2", 0),
            "layer3_clustered": funnel.get("layer3", 0),
            "layer4_passed": funnel.get("layer4", 0),
            "final_recommended": funnel.get("final", 0),
            "funnel": funnel,
        }
