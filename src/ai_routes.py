"""
ai_routes.py  —  Add these routes to your existing FastAPI backend
─────────────────────────────────────────────────────────────────
Exposes two ML model endpoints used by the EVA dashboard:

  POST /predict/digit  — MNIST handwritten digit classifier (Keras)
  POST /predict/ipl    — IPL match winner predictor (XGBoost / best model)

How to integrate:
  In your main.py:
    from ai_routes import router as ai_router
    app.include_router(ai_router)
"""

import io
import base64
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional


router = APIRouter()

# ══════════════════════════════════════════════════════════════
#  SHARED: lazy model loading (models load once on first call)
# ══════════════════════════════════════════════════════════════

_digit_model = None   # Keras model
_ipl_bundle  = None   # dict with model, match_df, helpers


def _load_digit_model():
    global _digit_model
    if _digit_model is None:
        from tensorflow import keras
        # Path to your saved Keras model — save it from the notebook with:
        #   model.save('models/digit_model.keras')
        _digit_model = keras.models.load_model('models/digit_model.keras')
        print('✅ Digit model loaded')
    return _digit_model


def _load_ipl_bundle():
    """
    Load everything the IPL predictor needs.
    Call this AFTER running your notebook cells (or re-run them here).
    The notebook must save the trained model and match_df first — see below.
    """
    global _ipl_bundle
    if _ipl_bundle is None:
        import pickle, pandas as pd
        # These files are created by adding the save cells below to your notebook
        with open('models/ipl_model.pkl', 'rb') as f:
            model = pickle.load(f)
        with open('models/ipl_match_df.pkl', 'rb') as f:
            match_df = pickle.load(f)
        with open('models/ipl_best_name.txt') as f:
            best_name = f.read().strip()

        _ipl_bundle = {
            'model':    model,
            'match_df': match_df,
            'name':     best_name,
        }
        print(f'✅ IPL model loaded: {best_name}')
    return _ipl_bundle


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 1 — Digit Classifier
# ══════════════════════════════════════════════════════════════

class DigitRequest(BaseModel):
    image: str   # base64-encoded PNG (from canvas.toDataURL)


class DigitResponse(BaseModel):
    digit: int
    confidence: float
    probabilities: list[float]


@router.post('/predict/digit', response_model=DigitResponse)
async def predict_digit(req: DigitRequest):
    try:
        from PIL import Image as PILImage

        # 1. Decode base64 → PIL image
        img_bytes = base64.b64decode(req.image)
        img = PILImage.open(io.BytesIO(img_bytes)).convert('L')   # grayscale

        # 2. Resize to 28×28 (MNIST format)
        img = img.resize((28, 28), PILImage.LANCZOS)

        # 3. Normalize: canvas is white-on-black already; MNIST expects white digit on black
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = arr.reshape(1, 784)    # flatten to match Dense model input

        # 4. Predict
        model  = _load_digit_model()
        probs  = model.predict(arr, verbose=0)[0].tolist()
        digit  = int(np.argmax(probs))
        conf   = float(probs[digit])

        return DigitResponse(digit=digit, confidence=conf, probabilities=probs)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 2 — IPL Match Predictor
# ══════════════════════════════════════════════════════════════

class IPLRequest(BaseModel):
    team1:         str              # batting first
    team2:         str              # chasing
    venue:         str
    toss_winner:   Optional[str] = ''
    toss_decision: Optional[str] = 'bat'
    is_knockout:   Optional[int] = 0
    season:        Optional[int] = 2026


class IPLResponse(BaseModel):
    winner:     str
    team1_prob: float
    team2_prob: float
    features:   dict
    model_used: str


@router.post('/predict/ipl', response_model=IPLResponse)
async def predict_ipl(req: IPLRequest):
    try:
        import pandas as pd

        bundle   = _load_ipl_bundle()
        model    = bundle['model']
        match_df = bundle['match_df']

        # ── Reproduce the feature helpers from the notebook ──────────────
        def win_rate(team, matches):
            if len(matches) == 0: return 0.5
            w = ((matches['team1'] == team) & (matches['team1_won'] == 1)).sum() + \
                ((matches['team2'] == team) & (matches['team1_won'] == 0)).sum()
            return w / len(matches)

        def streak(team):
            m = match_df[(match_df['team1'] == team) | (match_df['team2'] == team)]
            if len(m) == 0: return 0
            s = 0
            for _, r in m.iloc[::-1].iterrows():
                won = (r['team1'] == team and r['team1_won'] == 1) or \
                      (r['team2'] == team and r['team1_won'] == 0)
                if s == 0: s = 1 if won else -1
                elif (s > 0 and won) or (s < 0 and not won): s += (1 if won else -1)
                else: break
            return s

        def get_wr(team):
            m = match_df[(match_df['team1'] == team) | (match_df['team2'] == team)]
            return win_rate(team, m)

        def get_swr(team, season=2025):
            m = match_df[(match_df['season'] == season) &
                         ((match_df['team1'] == team) | (match_df['team2'] == team))]
            return win_rate(team, m)

        def get_form(team, n=5):
            m = match_df[(match_df['team1'] == team) | (match_df['team2'] == team)].tail(n)
            return win_rate(team, m)

        def get_bat(team):
            m = match_df[match_df['team1'] == team]
            return m['team1_won'].mean() if len(m) > 0 else 0.5

        def get_chase(team):
            m = match_df[match_df['team2'] == team]
            return (m['team1_won'] == 0).mean() if len(m) > 0 else 0.5

        def get_h2h(t1, t2):
            m = match_df[
                ((match_df['team1'] == t1) & (match_df['team2'] == t2)) |
                ((match_df['team1'] == t2) & (match_df['team2'] == t1))
            ]
            if len(m) == 0: return 0.5
            w = ((m['team1'] == t1) & (m['team1_won'] == 1)).sum() + \
                ((m['team2'] == t1) & (m['team1_won'] == 0)).sum()
            return w / len(m)

        def get_vwr(team, venue):
            m = match_df[(match_df['venue'] == venue) &
                         ((match_df['team1'] == team) | (match_df['team2'] == team))]
            return win_rate(team, m)

        def get_vavg(venue):
            m = match_df[match_df['venue'] == venue]
            return 150.0 if len(m) == 0 else float(
                m.get('venue_avg', pd.Series([150.0])).mean()
            )

        t1, t2 = req.team1, req.team2

        feat_dict = {
            'wr_diff':    get_wr(t1)     - get_wr(t2),
            'swr_diff':   get_swr(t1)    - get_swr(t2),
            'f5_diff':    get_form(t1,5) - get_form(t2,5),
            'f10_diff':   get_form(t1,10)- get_form(t2,10),
            'bat_diff':   get_bat(t1)    - get_bat(t2),
            'ch_diff':    get_chase(t1)  - get_chase(t2),
            'str_diff':   streak(t1)     - streak(t2),
            'h2h_diff':   get_h2h(t1,t2) - 0.5,
            't1_vwr':     get_vwr(t1, req.venue),
            'venue_avg':  get_vavg(req.venue),
            'season':     req.season,
            'is_knockout':req.is_knockout,
        }

        FEATURES = [
            'wr_diff','swr_diff','f5_diff','f10_diff',
            'bat_diff','ch_diff','str_diff','h2h_diff',
            't1_vwr','venue_avg','season','is_knockout'
        ]

        X = pd.DataFrame([feat_dict])[FEATURES]
        proba     = model.predict_proba(X)[0]   # [p_team2_wins, p_team1_wins]
        p_t1      = float(proba[1])
        p_t2      = float(proba[0])
        winner    = t1 if p_t1 > p_t2 else t2

        # Expose the most interpretable features to the frontend
        exposed = {
            'win_rate_diff':    round(feat_dict['wr_diff'],   3),
            'recent_form_diff': round(feat_dict['f5_diff'],   3),
            'h2h_diff':         round(feat_dict['h2h_diff'],  3),
            'venue_wr':         round(feat_dict['t1_vwr'],    3),
        }

        return IPLResponse(
            winner=winner, team1_prob=p_t1, team2_prob=p_t2,
            features=exposed, model_used=bundle['name']
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
#  NOTEBOOK SAVE CELLS  (paste into your notebooks to save models)
# ══════════════════════════════════════════════════════════════
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASTE THIS AT THE END OF Classify_Handwritten_Digits.ipynb
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import os
os.makedirs('models', exist_ok=True)
model.save('models/digit_model.keras')
print('✅ Digit model saved to models/digit_model.keras')

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASTE THIS AT THE END OF ipl-prediction.ipynb
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import os, pickle
os.makedirs('models', exist_ok=True)

best_clf = models[best_model_name]   # sklearn-compatible model
with open('models/ipl_model.pkl', 'wb') as f:
    pickle.dump(best_clf, f)

with open('models/ipl_match_df.pkl', 'wb') as f:
    pickle.dump(match_df, f)

with open('models/ipl_best_name.txt', 'w') as f:
    f.write(best_model_name)

print(f'✅ IPL model ({best_model_name}) + match_df saved to models/')
"""
