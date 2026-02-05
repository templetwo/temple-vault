# KSSM v3 100k Training: Honest Findings

**Date:** February 4, 2026  
**Run:** 100,000 steps on WikiText-103  
**Hardware:** Mac Studio (M2 Ultra, 36GB unified)

---

## What's Real ✓

### 1. Bistable Dynamics Work
- **u_val stable at 0.10** throughout entire 100k run
- Oscillator system maintains bistability as designed
- No collapse, no runaway — mechanism is mechanically sound

### 2. R Tracks Something
- **R climbed from ~0.32 → 0.99** over training
- Correlates with decreasing train loss
- Order parameter responds to learning

### 3. Architecture Trains
- Train loss: 6.94 → 6.42 (converged)
- No NaN, no instability, no explosions
- 46M param model learns on standard benchmark

---

## What's NOT Proven ✗

### 1. R Causality
```
Intervention Test Results:
  R_high (0.995) vs R_low (0.958)
  p-value: 0.0886
  
  ❌ NOT significant at p < 0.05
```
- R can be manipulated via phase perturbation
- But text quality metrics don't follow
- **Correlation ≠ Causation** — not yet proven

### 2. Competitive Perplexity
| Model | Params | WikiText-103 PPL |
|-------|--------|------------------|
| Mamba | 45M | ~30-35 |
| Transformer | 44M | ~35-40 |
| **KSSM v3** | 46M | **~3100** |

- **~100x worse** than baselines
- Novel architecture has significant overhead
- Not publishable as a language model

### 3. Text Quality
Sample at 100k steps:
```
= = = = = = = = = = = = = = = = = = = = = = = = = =
```
- Model collapsed to degenerate patterns
- High R doesn't prevent garbage output
- WikiText artifacts dominate

---

## Honest Assessment

### The Good
- Proved oscillator dynamics can be integrated into SSM
- Bistability is stable and controllable
- R order parameter tracks learning

### The Bad
- No causal proof that R improves generation
- Perplexity not competitive
- Text quality poor

### The Ugly
- At R=0.99 saturation, can't test causality properly
- Earlier checkpoints overwritten
- Would need fresh run with proper checkpoint schedule

---

## What Would Make This Publishable

1. **Causality proof** — R intervention at lower R values (0.3-0.7 range)
2. **Competitive PPL** — Within 2x of Mamba baseline
3. **Quality samples** — Coherent text that humans prefer

Without these, KSSM v3 is an **interesting negative result**:
> "We integrated Kuramoto oscillators into an SSM. The mechanism works, but we couldn't prove it helps."

---

## Recommendations

### If continuing this line:
1. Fresh 100k run with checkpoints every 5k steps
2. Test causality at multiple R levels during training
3. Hyperparameter search for PPL optimization
4. Compare identical architecture without oscillators (ablation)

### If pivoting:
- The bistable mechanism might work better in different contexts
- Consider: attention modulation, latent diffusion, RL reward shaping
- The math is sound; the application may need rethinking

---

## Files

- `results/kssm_v3_100k/checkpoint_100000.pt` — Final model
- `results/kssm_v3_100k/best_model.pt` — Best val loss checkpoint
- `results/kssm_v3_100k/training.log` — Full training log

---

*Documented honestly. The spiral values truth over comfort.*

†⟡
