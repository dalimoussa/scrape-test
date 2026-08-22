import re
import time
import json
from datetime import datetime, timedelta
import pytz

from flask_cors import CORS
from flask import Flask, request, Response, jsonify

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# =============================================================================
# DUAL DATA STORE: LIVE + PREMATCH
# =============================================================================
LIVE_DATA = {
    "_sports": {},
    "_by_oi": {},
    "_stats_by_oi": {},
}
LIVE_SUFFIX = "_1_3"

PREMATCH_DATA = {
    "_sports": {},
    "_by_oi": {},
}
PREMATCH_SUFFIX = "_1_1"

DATA = LIVE_DATA
SUFFIX = LIVE_SUFFIX

SOCCER_STAT_FIELDS = {
    "S0": "Goal",
    "S1": "Corner",
    "S2": "YellowCard",
    "S3": "RedCard",
    "S4": "ThrowIn",
    "S5": "FreeKick",
    "S6": "GoalKick",
    "S7": "Penalty",
    "S8": "Substitution",
}


def empty_live_store():
    return {
        "_sports": {},
        "_by_oi": {},
        "_stats_by_oi": {},
    }


def empty_prematch_store():
    return {
        "_sports": {},
        "_by_oi": {},
    }


def pretty_json(data):
    """Return formatted, UTF-8 JSON Response."""
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8"
    )


def frac_to_dec(od_str):
    """Convert fractional odds like '5/2' to decimal 3.50."""
    if not od_str:
        return None
    od_str = str(od_str).strip()
    if "/" in od_str:
        parts = od_str.split("/")
        try:
            num = float(parts[0])
            den = float(parts[1])
            if den != 0:
                return round((num / den) + 1.0, 2)
        except Exception:
            return None
    try:
        return round(float(od_str), 2)
    except Exception:
        return None


def parse_teams(event_name):
    """Extract home and away teams cleanly."""
    if not event_name:
        return {"home": "", "away": ""}
    # Don't treat API route paths as team names
    if str(event_name).startswith("/") or "api/" in str(event_name).lower():
        return {"home": "", "away": ""}
    for sep in (" v ", " vs ", " - ", " V ", " VS "):
        if sep in str(event_name):
            parts = str(event_name).split(sep, 1)
            h = parts[0].strip()
            a = parts[1].strip()
            if h and a:
                return {"home": h, "away": a}
    return {"home": "", "away": ""}


def parse_scores(score_str):
    """Extract home and away score numbers."""
    if not score_str:
        return {"home": None, "away": None, "display": ""}
    s = str(score_str).strip()
    for sep in (" - ", "-", " "):
        if sep in s:
            parts = s.split(sep, 1)
            try:
                h = int(parts[0].strip())
                a = int(parts[1].strip())
                return {"home": h, "away": a, "display": f"{h} - {a}"}
            except Exception:
                pass
    return {"home": None, "away": None, "display": s}


def apply_language_id(language_id):
    """Set suffixes from GamingContext.languageId; migrate matching event buckets."""
    global LIVE_DATA, PREMATCH_DATA, LIVE_SUFFIX, PREMATCH_SUFFIX, DATA, SUFFIX
    try:
        lid = int(language_id)
    except (TypeError, ValueError):
        return
    live_tail = 3 if lid == 1 else 0
    prematch_tail = 1
    new_live_suffix = f"_{lid}_{live_tail}"
    new_prematch_suffix = f"_{lid}_{prematch_tail}"

    if new_live_suffix == LIVE_SUFFIX and new_prematch_suffix == PREMATCH_SUFFIX:
        return

    old_live = LIVE_DATA
    old_prematch = PREMATCH_DATA

    LIVE_SUFFIX = new_live_suffix
    PREMATCH_SUFFIX = new_prematch_suffix
    SUFFIX = LIVE_SUFFIX
    DATA = LIVE_DATA

    # Migrate live store
    LIVE_DATA = empty_live_store()
    LIVE_DATA["_sports"] = old_live.get("_sports", {}) or {}
    LIVE_DATA["_stats_by_oi"] = old_live.get("_stats_by_oi", {}) or {}
    for key, val in old_live.items():
        if key in ("_sports", "_by_oi", "_stats_by_oi"):
            continue
        if isinstance(val, list) and key.startswith("C"):
            LIVE_DATA[key] = val
        elif isinstance(val, dict):
            LIVE_DATA[key] = val
            oi = val.get("OI")
            if oi:
                LIVE_DATA.setdefault("_by_oi", {})[str(oi)] = key

    # Migrate pre-match store
    PREMATCH_DATA = empty_prematch_store()
    PREMATCH_DATA["_sports"] = old_prematch.get("_sports", {}) or {}
    for key, val in old_prematch.items():
        if key in ("_sports", "_by_oi"):
            continue
        if isinstance(val, list) and key.startswith("C"):
            PREMATCH_DATA[key] = val
        elif isinstance(val, dict):
            PREMATCH_DATA[key] = val
            oi = val.get("OI")
            if oi:
                PREMATCH_DATA.setdefault("_by_oi", {})[str(oi)] = key

    DATA = LIVE_DATA
    SUFFIX = LIVE_SUFFIX


def to_dit(txt):
    """Parse text data into dict format."""
    dit = {}
    try:
        data = txt[:-1].split(';')
        for item in data:
            arr = item.split('=')
            if len(arr) > 1:
                dit[arr[0]] = arr[1]
    except Exception as e:
        print(f"Error in to_dit: {txt}")
    return dit


def parse_ev_it(it, suffix=None, default_sport=None):
    """Extract sport_id and category_key flexibly from IT field."""
    if it:
        m = re.search(r"C(\d+)", str(it))
        if m:
            sport_id = m.group(1)
            sfx = suffix if suffix is not None else SUFFIX
            return sport_id, f"C{sport_id}A{sfx}"
    
    if default_sport:
        sport_id = str(default_sport)
        sfx = suffix if suffix is not None else SUFFIX
        return sport_id, f"C{sport_id}A{sfx}"
        
    return None, None


def ensure_category(category_key, store=None):
    store = store if store is not None else DATA
    if category_key not in store or not isinstance(store.get(category_key), list):
        store[category_key] = []
    return store[category_key]


def handle_insert(it, data_obj, category_key, store=None):
    """Insert EV into category list and index OI."""
    store = store if store is not None else DATA
    ensure_category(category_key, store)
    if "markets" not in data_obj or not isinstance(data_obj.get("markets"), list):
        data_obj["markets"] = []
    if it not in store[category_key]:
        store[category_key].append(it)
    if it not in store or not isinstance(store.get(it), dict):
        store[it] = data_obj
    else:
        markets = store[it].get("markets") if isinstance(store[it], dict) else None
        store[it].update(data_obj)
        if markets and not store[it].get("markets"):
            store[it]["markets"] = markets
    ev = store[it]
    for fid in (data_obj.get("OI"), data_obj.get("C3"), ev.get("OI"), ev.get("C3"), data_obj.get("ID"), ev.get("ID"), data_obj.get("C2"), ev.get("C2")):
        if fid:
            store.setdefault("_by_oi", {})[str(fid)] = it
    # Extract fixture number from key M{id}...
    m_num = re.search(r"M(\d+)", str(it))
    if m_num:
        store.setdefault("_by_oi", {})[m_num.group(1)] = it

    # Merge stats only for live store
    if "_stats_by_oi" in store:
        merge_pending_stats(
            ev,
            ev.get("OI") or data_obj.get("OI") or ev.get("C3") or data_obj.get("C3"),
            store
        )


def register_sport_from_cl(data_obj, store=None):
    store = store if store is not None else DATA
    sport_id = data_obj.get("CL") or data_obj.get("ID")
    if sport_id is None or sport_id == "":
        return
    sport_id = str(sport_id)
    name = data_obj.get("NA") or ""
    # Filter out API paths from sport names
    if name.startswith("/") or "api/" in name.lower():
        name = ""
    sports = store.setdefault("_sports", {})
    sports[sport_id] = {
        "id": sport_id,
        "name": name or sports.get(sport_id, {}).get("name") or f"Sport {sport_id}",
        "it": data_obj.get("IT") or sports.get(sport_id, {}).get("it") or "",
    }


def find_ev_by_oi(oi, store=None):
    store = store if store is not None else DATA
    if not oi:
        return None, None
    it = (store.get("_by_oi") or {}).get(str(oi))
    if it and isinstance(store.get(it), dict):
        return it, store[it]
    if str(oi) in store and isinstance(store[str(oi)], dict):
        return str(oi), store[str(oi)]
    # Scan keys with M{oi}
    for k, v in store.items():
        if isinstance(v, dict) and (k == str(oi) or k.startswith(f"M{oi}") or v.get("OI") == str(oi) or v.get("C2") == str(oi)):
            return k, v
    return None, None


def parse_home_away(val):
    """Parse 'home,away' into {home, away}."""
    if val is None or val == "":
        return {"home": None, "away": None}
    parts = str(val).split(",")
    home_raw = parts[0] if len(parts) > 0 else ""
    away_raw = parts[1] if len(parts) > 1 else ""

    def to_num(x):
        if x is None or x == "":
            return None
        try:
            return int(x)
        except ValueError:
            try:
                return float(x)
            except ValueError:
                return x

    return {"home": to_num(home_raw), "away": to_num(away_raw)}


def stats_from_dit(dit):
    stats = {}
    for sk, name in SOCCER_STAT_FIELDS.items():
        if sk in dit:
            stats[name] = parse_home_away(dit.get(sk))
    return stats


def ovsf_fixture_id(it_or_key, dit=None):
    text = str(it_or_key or "")
    m = re.search(r"OVSF(\d+)", text)
    if m:
        return m.group(1)
    if dit:
        it = dit.get("IT") or ""
        m = re.search(r"OVSF(\d+)", it)
        if m:
            return m.group(1)
        if dit.get("ID"):
            return str(dit.get("ID"))
    return None


def apply_soccer_stats(oi, dit, replace=False):
    oi = str(oi or "")
    if not oi:
        return
    stats = stats_from_dit(dit)
    if not stats and not replace:
        return
    store = LIVE_DATA.setdefault("_stats_by_oi", {})
    if replace:
        store[oi] = stats
    else:
        store.setdefault(oi, {}).update(stats)
    it, ev = find_ev_by_oi(oi, LIVE_DATA)
    if ev is not None:
        ev["stats"] = dict(store[oi])
        LIVE_DATA.setdefault("_by_oi", {})[oi] = it


def merge_pending_stats(ev, oi, store=None):
    store = store if store is not None else DATA
    if not isinstance(ev, dict):
        return
    if "_stats_by_oi" not in store:
        return
    stats_store = store.get("_stats_by_oi") or {}
    keys = []
    if oi:
        keys.append(str(oi))
    for k in (ev.get("OI"), ev.get("C3")):
        if k and str(k) not in keys:
            keys.append(str(k))
    merged = {}
    for k in keys:
        if k in stats_store:
            merged.update(stats_store[k])
    if merged:
        ev["stats"] = merged


def reattach_all_soccer_stats():
    store = LIVE_DATA.get("_stats_by_oi") or {}
    if not store:
        return
    cat = f"C1A{LIVE_SUFFIX}"
    for ev_it in (LIVE_DATA.get(cat) or []):
        ev = LIVE_DATA.get(ev_it)
        if not isinstance(ev, dict):
            continue
        merge_pending_stats(ev, ev.get("OI") or ev.get("C3"), LIVE_DATA)


def init_ovs1(txt):
    LIVE_DATA["_stats_by_oi"] = {}
    cat = f"C1A{LIVE_SUFFIX}"
    for ev_it in (LIVE_DATA.get(cat) or []):
        ev = LIVE_DATA.get(ev_it)
        if isinstance(ev, dict):
            ev.pop("stats", None)
    for item in str(txt).split("|")[1:]:
        if not item or len(item) < 2:
            continue
        if item[:2] != "EV":
            continue
        dit = to_dit(item[3:] if len(item) > 3 else "")
        oi = ovsf_fixture_id(dit.get("IT"), dit)
        if oi:
            apply_soccer_stats(oi, dit, replace=True)


def attach_market(data_obj, store=None):
    store = store if store is not None else DATA
    market_name = data_obj.get("NA") or ""
    # Filter out API paths
    if market_name.startswith("/") or "api/" in market_name.lower():
        return

    oi = data_obj.get("FI") or data_obj.get("ID")
    it, ev = find_ev_by_oi(oi, store)
    if not ev:
        return
    markets = ev.setdefault("markets", [])
    market = {
        "id": data_obj.get("ID") or data_obj.get("MA") or "",
        "ma": data_obj.get("MA") or data_obj.get("ID") or "",
        "name": market_name or "Full Time Result",
        "it": data_obj.get("IT") or "",
        "su": data_obj.get("SU"),
        "odds": [],
    }
    markets.append(market)
    ev["_current_market_idx"] = len(markets) - 1


def attach_odds(data_obj, store=None):
    store = store if store is not None else DATA
    oi = data_obj.get("FI") or data_obj.get("ID")
    it, ev = find_ev_by_oi(oi, store)
    if not ev:
        return
    markets = ev.get("markets") or []
    if not markets:
        # Create default market if missing
        markets = [{"id": "1", "name": "Full Time Result", "odds": []}]
        ev["markets"] = markets
        ev["_current_market_idx"] = 0
    idx = ev.get("_current_market_idx")
    if idx is None or idx < 0 or idx >= len(markets):
        idx = len(markets) - 1
    markets[idx].setdefault("odds", []).append({
        "id": data_obj.get("ID") or "",
        "od": data_obj.get("OD") or "",
        "or": data_obj.get("OR"),
        "ha": data_obj.get("HA") or data_obj.get("HD") or "",
        "na": data_obj.get("NA") or "",
        "su": data_obj.get("SU"),
        "it": data_obj.get("IT") or "",
    })


def update_data(target_key, txt, store=None, suffix=None):
    store = store if store is not None else DATA
    sfx = suffix if suffix is not None else SUFFIX
    if "|" not in str(txt):
        return
    action_name, action_data = txt.split("|", 1)

    if action_name == "U":
        dit = to_dit(action_data)
        oi = ovsf_fixture_id(target_key)
        if oi and "_stats_by_oi" in store:
            apply_soccer_stats(oi, dit)
            return
        key = target_key
        if not (store.get(key) and isinstance(store.get(key), dict)):
            key = str(target_key).split("/")[-1]
        if isinstance(store.get(key), dict):
            markets = store[key].get("markets")
            cur_idx = store[key].get("_current_market_idx")
            stats = store[key].get("stats")
            store[key].update(dit)
            if markets is not None and "markets" not in dit:
                store[key]["markets"] = markets
            if cur_idx is not None and "_current_market_idx" not in dit:
                store[key]["_current_market_idx"] = cur_idx
            if stats is not None and "stats" not in dit:
                store[key]["stats"] = stats
            oi = store[key].get("OI")
            if oi:
                store.setdefault("_by_oi", {})[str(oi)] = key

    elif action_name == "I":
        if len(action_data) < 2:
            return
        data_type = action_data[:2]
        dit = to_dit(action_data[3:] if len(action_data) > 3 else "")
        if data_type == "EV":
            it = dit.get("IT") or ""
            oi = ovsf_fixture_id(it, dit)
            if oi and it.startswith("OVSF"):
                apply_soccer_stats(oi, dit, replace=True)
                return
            sport_id, category_key = parse_ev_it(it, sfx, dit.get("CL") or dit.get("ID"))
            if not it or not category_key:
                return
            dit["_sportId"] = sport_id
            handle_insert(it, dit, category_key, store)
        elif data_type == "CL":
            register_sport_from_cl(dit, store)
        elif data_type == "MA":
            attach_market(dit, store)
        elif data_type == "PA":
            attach_odds(dit, store)

    elif action_name == "D":
        it = str(target_key).split("/")[-1]
        sport_id, category_key = parse_ev_it(it, sfx)
        keys = []
        if category_key:
            keys.append(category_key)
        else:
            keys = [k for k, v in store.items() if isinstance(v, list) and k.startswith("C")]
        for key in keys:
            lst = store.get(key)
            if isinstance(lst, list) and it in lst:
                lst.remove(it)
        ev = store.get(it)
        if isinstance(ev, dict):
            oi = ev.get("OI")
            if oi and str(oi) in (store.get("_by_oi") or {}):
                del store["_by_oi"][str(oi)]
        if it in store:
            del store[it]


def init_data(txt, store=None, suffix=None):
    store = store if store is not None else DATA
    sfx = suffix if suffix is not None else SUFFIX
    lst = str(txt).split("|")[1:]
    current_ev_it = None
    current_sport_id = "1"

    for item in lst:
        if not item or len(item) < 2:
            continue
        data_type = item[:2]
        data_obj = to_dit(item[3:] if len(item) > 3 else "")

        if data_type == "CL":
            register_sport_from_cl(data_obj, store)
            current_sport_id = data_obj.get("ID") or data_obj.get("CL") or current_sport_id
            continue

        it = data_obj.get("IT") or data_obj.get("OI") or data_obj.get("ID")
        if data_type == "EV":
            # Filter out non-event items
            name = data_obj.get("NA") or ""
            if name.startswith("/") or "api/" in name.lower():
                continue

            sport_id, category_key = parse_ev_it(it, sfx, current_sport_id)
            if not sport_id:
                sport_id = str(current_sport_id)
                category_key = f"C{sport_id}A{sfx}"
            
            if not it:
                it = f"EV_{data_obj.get('OI') or len(store)}"
                
            data_obj["_sportId"] = str(sport_id)
            handle_insert(it, data_obj, category_key, store)
            current_ev_it = it
            continue

        if data_type == "MA":
            if data_obj.get("FI"):
                attach_market(data_obj, store)
            elif current_ev_it and isinstance(store.get(current_ev_it), dict):
                data_obj["FI"] = store[current_ev_it].get("OI") or current_ev_it
                attach_market(data_obj, store)
            continue

        if data_type == "PA":
            if data_obj.get("FI"):
                attach_odds(data_obj, store)
            elif current_ev_it and isinstance(store.get(current_ev_it), dict):
                data_obj["FI"] = store[current_ev_it].get("OI") or current_ev_it
                attach_odds(data_obj, store)
            continue


def resolve_delta_store(action_key, action_val, msg_type):
    """Determine which store (live vs prematch) a \\x15 delta update belongs to."""
    key = str(action_key).split("/")[-1] if action_key else ""

    if key:
        if isinstance(PREMATCH_DATA.get(key), (dict, list)):
            return PREMATCH_DATA, PREMATCH_SUFFIX
        if isinstance(LIVE_DATA.get(key), (dict, list)):
            return LIVE_DATA, LIVE_SUFFIX

    if "SS=" in str(action_val) or "TM=" in str(action_val) or "TT=" in str(action_val):
        return LIVE_DATA, LIVE_SUFFIX

    ak = str(action_key or "")
    if PREMATCH_SUFFIX and PREMATCH_SUFFIX in ak:
        return PREMATCH_DATA, PREMATCH_SUFFIX
    if LIVE_SUFFIX and LIVE_SUFFIX in ak:
        return LIVE_DATA, LIVE_SUFFIX

    oi = None
    ovsf_m = re.search(r"OVSF(\d+)", ak)
    if ovsf_m:
        oi = ovsf_m.group(1)
    if not oi:
        fi_m = re.search(r"FI=(\d+)", str(action_val or ""))
        if fi_m:
            oi = fi_m.group(1)
    if oi:
        if str(oi) in (PREMATCH_DATA.get("_by_oi") or {}):
            return PREMATCH_DATA, PREMATCH_SUFFIX
        if str(oi) in (LIVE_DATA.get("_by_oi") or {}):
            return LIVE_DATA, LIVE_SUFFIX

    if msg_type == "prematch":
        return PREMATCH_DATA, PREMATCH_SUFFIX
    if msg_type == "live":
        return LIVE_DATA, LIVE_SUFFIX

    return LIVE_DATA, LIVE_SUFFIX


def data_parse(txt, msg_type='live'):
    global DATA, SUFFIX
    if not txt or not txt.startswith(('\x15', '\x14')):
        return
    item_arr = txt.split('|\x08')
    for item in item_arr:
        item = item.strip()
        if not item:
            continue
        action_item = item[1:].split('\x01', 1)
        if len(action_item) < 2:
            continue
        action_key = action_item[0]
        action_val = action_item[1]

        # LIVE IN-PLAY SNAPSHOT
        if item.startswith('\x14OVInPlay_') or (msg_type == 'live' and item.startswith('\x14') and 'SS=' in action_val and 'TM=' in action_val):
            preserved_stats = LIVE_DATA.get("_stats_by_oi") or {}
            LIVE_DATA.clear()
            LIVE_DATA.update(empty_live_store())
            LIVE_DATA["_stats_by_oi"] = preserved_stats
            DATA = LIVE_DATA
            SUFFIX = LIVE_SUFFIX
            init_data(action_val, LIVE_DATA, LIVE_SUFFIX)
            reattach_all_soccer_stats()
            
        # LIVE SOCCER TECH STATS
        elif item.startswith('\x14OVS1') or action_key.startswith('OVS1'):
            DATA = LIVE_DATA
            SUFFIX = LIVE_SUFFIX
            if item.startswith('\x14') or str(action_val).startswith('F|') or str(action_val).startswith('|'):
                init_ovs1(action_val)
            else:
                update_data(action_key, action_val, LIVE_DATA, LIVE_SUFFIX)
                
        # PRE-MATCH / COUPON / OTHER SNAPSHOTS
        elif item.startswith('\x14'):
            if msg_type == 'live' and ('SS=' in action_val or 'OVInPlay' in item):
                init_data(action_val, LIVE_DATA, LIVE_SUFFIX)
            else:
                init_data(action_val, PREMATCH_DATA, PREMATCH_SUFFIX)
                
        # INCREMENTAL DELTAS
        elif item.startswith('\x15'):
            store, sfx = resolve_delta_store(action_key, action_val, msg_type)
            DATA = store
            SUFFIX = sfx
            update_data(action_key, action_val, store, sfx)


def _safe_int(val, default=0):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def parse_utc_timestamp(tu_str):
    if not tu_str:
        return None
    try:
        dt = datetime.strptime(str(tu_str).strip(), "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=pytz.utc).timestamp()
    except Exception:
        return None


def parse_scheduled_time(info):
    """Extract scheduled kickoff from SM (Unix timestamp) or TU (UTC string)."""
    sm = info.get("SM")
    if sm:
        try:
            ts = int(sm)
            dt = datetime.fromtimestamp(ts, pytz.utc)
            return dt.isoformat().replace("+00:00", "Z"), dt.strftime("%d %b %H:%M UTC")
        except Exception:
            pass
    tu = info.get("TU")
    if tu:
        try:
            dt = datetime.strptime(str(tu).strip(), "%Y%m%d%H%M%S").replace(tzinfo=pytz.utc)
            return dt.isoformat().replace("+00:00", "Z"), dt.strftime("%d %b %H:%M UTC")
        except Exception:
            pass
    return None, "TBA"


def soccer_time_and_period(info):
    """Accurate UTC soccer time calculation."""
    TU = info.get("TU") or ""
    TT = _safe_int(info.get("TT"))
    TS = _safe_int(info.get("TS"))
    TM = _safe_int(info.get("TM"))
    MD = info.get("MD") or "0"
    league = info.get("CT") or ""

    if not TU:
        rel_time_set = f"{TM}:{str(TS).zfill(2)}"
    else:
        begin_ts = parse_utc_timestamp(TU)
        if begin_ts is None:
            rel_time_set = f"{TM}:{str(TS).zfill(2)}"
        else:
            now_ts = datetime.now(pytz.utc).timestamp()
            elapsed_sec = max(0, int(now_ts - begin_ts))
            if TM == 0 and TT == 0:
                rel_time_set = "00:00"
            elif TT == 1:
                cur_min = TM + (elapsed_sec // 60)
                cur_sec = (TS + (elapsed_sec % 60)) % 60
                rel_time_set = f"{cur_min}:{str(cur_sec).zfill(2)}"
            else:
                rel_time_set = f"{TM}:{str(TS).zfill(2)}"

    if "Esoccer" in league and "mins play" in league:
        try:
            total_mins = int(league.split(" - ")[1].split(" ")[0])
        except Exception:
            total_mins = 90
    else:
        total_mins = 90

    if TM == total_mins // 2 and TS == 0 and TT == 0 and MD == "1":
        period = "HalfTime"
    elif TM == total_mins and TS == 0 and TT == 0 and MD == "1":
        period = "FullTime"
    elif TM == 0 and TS == 0 and TT == 0 and MD == "0":
        period = "ToStart"
    else:
        period = "FirstHalf" if MD == "0" else "SecondHalf"
    return rel_time_set, period


def basketball_time(info):
    """Basketball countdown timer."""
    TU = info.get("TU") or ""
    TT = _safe_int(info.get("TT"))
    TS = _safe_int(info.get("TS"))
    TM = _safe_int(info.get("TM"))
    try:
        begin_ts = parse_utc_timestamp(TU)
        if begin_ts is not None and TT == 1:
            now_ts = datetime.now(pytz.utc).timestamp()
            elapsed_sec = max(0, int(now_ts - begin_ts))
            total_sec = TM * 60 + TS - elapsed_sec
            if total_sec < 0:
                total_sec = 0
            return f"{total_sec // 60:02d}:{total_sec % 60:02d}"
        return f"{TM:02d}:{TS:02d}"
    except Exception:
        return f"{TM:02d}:{TS:02d}"


def generic_time(info):
    TM = info.get("TM")
    TS = info.get("TS")
    if TM in (None, "") and TS in (None, ""):
        return ""
    try:
        return f"{int(TM)}:{str(int(TS)).zfill(2)}"
    except Exception:
        return f"{TM}:{TS}"


def resolve_soccer_stats(info):
    if not isinstance(info, dict):
        return {}
    if info.get("stats"):
        return info["stats"]
    store = LIVE_DATA.get("_stats_by_oi") or {}
    for k in (info.get("OI"), info.get("C3")):
        if k and str(k) in store:
            return store[str(k)]
    return {}


def format_live_event(ev_it, info, sport_id):
    """Structured, readable live event representation."""
    teams = parse_teams(info.get("NA") or "")
    if not teams["home"] or not teams["away"]:
        return None

    sports = LIVE_DATA.get("_sports") or {}
    sport_meta = sports.get(str(sport_id), {})
    sport_name = sport_meta.get("name") or info.get("CL") or f"Sport {sport_id}"

    period = info.get("CP") or ""
    rel_time = ""

    if str(sport_id) == "1":
        try:
            rel_time, period = soccer_time_and_period(info)
        except Exception as e:
            rel_time = generic_time(info)
            period = period or info.get("MD") or ""
    elif str(sport_id) == "18":
        try:
            rel_time = basketball_time(info)
            period = info.get("CP") or period
        except Exception as e:
            rel_time = generic_time(info)
    else:
        rel_time = generic_time(info)
        if not period:
            period = info.get("EX") or info.get("MD") or ""

    scores = parse_scores(info.get("SS") or "")

    markets = []
    for m in (info.get("markets") or []):
        m_name = m.get("name") or ""
        if m_name.startswith("/") or "api/" in m_name.lower():
            continue
        odds_list = []
        for od in (m.get("odds") or []):
            fractional = od.get("od") or ""
            odds_list.append({
                "id": od.get("id") or "",
                "name": od.get("na") or "",
                "oddsDecimal": frac_to_dec(fractional),
                "oddsFractional": fractional,
                "handicap": od.get("ha") or "",
                "suspended": od.get("su") == "1",
                "order": od.get("or"),
            })
        markets.append({
            "id": m.get("id"),
            "name": m_name or "Full Time Result",
            "suspended": m.get("su") == "1",
            "odds": odds_list,
        })

    fid = info.get("OI") or info.get("C3") or info.get("ID") or ""
    m_num = re.search(r"M(\d+)", str(ev_it))
    if m_num and not fid:
        fid = m_num.group(1)

    out = {
        "id": info.get("C2") or info.get("ID") or str(ev_it),
        "fixtureId": str(fid),
        "sportId": str(sport_id),
        "sport": sport_name,
        "league": info.get("CT") or info.get("CB") or "",
        "event": info.get("NA") or "",
        "homeTeam": teams["home"],
        "awayTeam": teams["away"],
        "score": scores["display"],
        "homeScore": scores["home"],
        "awayScore": scores["away"],
        "period": period,
        "time": rel_time,
        "points": info.get("XP") or "",
        "phase": info.get("EX") or "",
        "serve": info.get("PI") or "",
        "markets": markets,
    }
    if str(sport_id) == "1":
        out["stats"] = resolve_soccer_stats(info)
    return out


def live_events_for_sport(sport_id):
    seen = set()
    live_lst = []
    keys = [k for k, v in LIVE_DATA.items() if isinstance(v, list) and (k == f"C{sport_id}" or k.startswith(f"C{sport_id}A") or k.startswith(f"C{sport_id}_"))]
    for cat_key in keys:
        for ev_it in (LIVE_DATA.get(cat_key) or []):
            info = LIVE_DATA.get(ev_it)
            if not isinstance(info, dict):
                continue
            fmt = format_live_event(ev_it, info, sport_id)
            if not fmt:
                continue
            dedup_key = (fmt["homeTeam"], fmt["awayTeam"])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            live_lst.append(fmt)

    for ev_it, info in LIVE_DATA.items():
        if isinstance(info, dict) and str(info.get("_sportId")) == str(sport_id):
            fmt = format_live_event(ev_it, info, sport_id)
            if not fmt:
                continue
            dedup_key = (fmt["homeTeam"], fmt["awayTeam"])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            live_lst.append(fmt)

    return live_lst


def format_prematch_event(ev_it, info, sport_id):
    """Structured pre-match event representation."""
    teams = parse_teams(info.get("NA") or "")
    if not teams["home"] or not teams["away"]:
        return None

    sports = PREMATCH_DATA.get("_sports") or {}
    sport_meta = sports.get(str(sport_id), {})
    sport_name = sport_meta.get("name") or info.get("CL") or f"Sport {sport_id}"

    scheduled_ts, scheduled_display = parse_scheduled_time(info)

    markets = []
    for m in (info.get("markets") or []):
        m_name = m.get("name") or ""
        if m_name.startswith("/") or "api/" in m_name.lower():
            continue
        odds_list = []
        for od in (m.get("odds") or []):
            fractional = od.get("od") or ""
            odds_list.append({
                "id": od.get("id") or "",
                "name": od.get("na") or "",
                "oddsDecimal": frac_to_dec(fractional),
                "oddsFractional": fractional,
                "handicap": od.get("ha") or "",
                "suspended": od.get("su") == "1",
                "order": od.get("or"),
            })
        markets.append({
            "id": m.get("id"),
            "name": m_name or "Full Time Result",
            "suspended": m.get("su") == "1",
            "odds": odds_list,
        })

    fid = info.get("OI") or info.get("C3") or info.get("ID") or ""
    m_num = re.search(r"M(\d+)", str(ev_it))
    if m_num and not fid:
        fid = m_num.group(1)

    return {
        "id": info.get("C2") or info.get("ID") or str(ev_it),
        "fixtureId": str(fid),
        "sportId": str(sport_id),
        "sport": sport_name,
        "league": info.get("CT") or info.get("CB") or "",
        "event": info.get("NA") or "",
        "homeTeam": teams["home"],
        "awayTeam": teams["away"],
        "scheduledTime": scheduled_ts,
        "scheduledDisplay": scheduled_display,
        "status": "prematch",
        "score": {"home": None, "away": None, "display": ""},
        "markets": markets,
    }


def prematch_events_for_sport(sport_id):
    seen = set()
    out = []
    # 1. Match category lists
    keys = [k for k, v in PREMATCH_DATA.items() if isinstance(v, list) and (k == f"C{sport_id}" or k.startswith(f"C{sport_id}A") or k.startswith(f"C{sport_id}_"))]
    for cat_key in keys:
        for ev_it in (PREMATCH_DATA.get(cat_key) or []):
            info = PREMATCH_DATA.get(ev_it)
            if not isinstance(info, dict):
                continue
            fmt = format_prematch_event(ev_it, info, sport_id)
            if not fmt:
                continue
            dedup_key = (fmt["homeTeam"], fmt["awayTeam"])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            out.append(fmt)

    # 2. Fallback scan by _sportId
    for ev_it, info in PREMATCH_DATA.items():
        if isinstance(info, dict) and str(info.get("_sportId")) == str(sport_id):
            fmt = format_prematch_event(ev_it, info, sport_id)
            if not fmt:
                continue
            dedup_key = (fmt["homeTeam"], fmt["awayTeam"])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            out.append(fmt)

    return out


def list_sport_ids(store=None):
    store = store if store is not None else LIVE_DATA
    ids = set((store.get("_sports") or {}).keys())
    for key, val in store.items():
        if isinstance(val, list) and key.startswith("C"):
            m = re.match(r"C(\d+)", key)
            if m:
                ids.add(m.group(1))
        elif isinstance(val, dict) and val.get("_sportId"):
            ids.add(str(val["_sportId"]))

    def sort_key(x):
        try:
            return (0, int(x))
        except Exception:
            return (1, str(x))
    return sorted(ids, key=sort_key)


def soccer_stats_list():
    out = []
    category_key = f"C1A{LIVE_SUFFIX}"
    for ev_it in (LIVE_DATA.get(category_key) or []):
        info = LIVE_DATA.get(ev_it)
        if not isinstance(info, dict):
            continue
        try:
            rel_time, period = soccer_time_and_period(info)
        except Exception:
            rel_time, period = generic_time(info), info.get("CP") or ""
        teams = parse_teams(info.get("NA") or "")
        if not teams["home"] or not teams["away"]:
            continue
        out.append({
            "fixtureId": info.get("OI") or info.get("C3") or "",
            "event": info.get("NA") or "",
            "homeTeam": teams["home"],
            "awayTeam": teams["away"],
            "league": info.get("CT") or "",
            "score": info.get("SS") or "",
            "time": rel_time,
            "period": period,
            "stats": resolve_soccer_stats(info),
        })
    return out


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/data', methods=['GET', 'POST'])
def handle_data():
    """Native data requests: POST from Chrome extension and GET for raw debug."""
    if request.method == 'POST':
        data = request.json or {}
        try:
            apply_language_id(data.get("lang"))
            msg_type = data.get("msgType", "prematch")
            data_parse(data.get("data", ""), msg_type)
        except Exception as e:
            print(f"Error parsing data: {e}")
        return "1"
    elif request.method == 'GET':
        return pretty_json({
            "live": LIVE_DATA,
            "prematch": PREMATCH_DATA,
            "liveSuffix": LIVE_SUFFIX,
            "prematchSuffix": PREMATCH_SUFFIX,
        })


@app.route('/sports', methods=['GET'])
def sports_list():
    """Sport categories and match count. ?scope=live|prematch"""
    scope = request.args.get("scope", "live")
    store = PREMATCH_DATA if scope == "prematch" else LIVE_DATA
    suffix = PREMATCH_SUFFIX if scope == "prematch" else LIVE_SUFFIX

    sports = store.get("_sports") or {}
    out = []
    ids = list_sport_ids(store)
    for sid in ids:
        meta = sports.get(str(sid), {})
        cat = f"C{sid}A{suffix}"
        count = len(prematch_events_for_sport(sid)) if scope == "prematch" else len(live_events_for_sport(sid))
        if count > 0:
            out.append({
                "id": str(sid),
                "name": meta.get("name") or f"Sport {sid}",
                "count": count,
                "category": cat,
            })
    return pretty_json(out)


@app.route('/live', methods=['GET'])
def live_events_api():
    """Visual, formatted, and readable live match data."""
    sport = request.args.get("sport")
    if sport:
        live_lst = live_events_for_sport(str(sport))
    else:
        live_lst = []
        for sid in list_sport_ids(LIVE_DATA):
            live_lst.extend(live_events_for_sport(sid))
    return pretty_json(live_lst)


@app.route('/prematch', methods=['GET'])
def prematch_events_api():
    """All pre-match fixtures with teams, scheduled time, competition, and markets/odds."""
    sport = request.args.get("sport")
    competition = request.args.get("competition")

    if sport:
        out = prematch_events_for_sport(str(sport))
    else:
        out = []
        for sid in list_sport_ids(PREMATCH_DATA):
            out.extend(prematch_events_for_sport(sid))

    if competition:
        comp_lower = competition.lower()
        out = [m for m in out if comp_lower in (m.get("league") or "").lower()]

    return pretty_json(out)


@app.route('/fixtures', methods=['GET'])
def fixtures_api():
    """Combined live + pre-match fixtures."""
    sport = request.args.get("sport")
    out = []

    if sport:
        out.extend(live_events_for_sport(str(sport)))
        out.extend(prematch_events_for_sport(str(sport)))
    else:
        for sid in list_sport_ids(LIVE_DATA):
            out.extend(live_events_for_sport(sid))
        for sid in list_sport_ids(PREMATCH_DATA):
            out.extend(prematch_events_for_sport(sid))

    return pretty_json(out)


@app.route('/soccer/stats', methods=['GET'])
def soccer_stats_api():
    """Returns soccer technical stats (corners, cards, shots, etc.)."""
    return pretty_json(soccer_stats_list())


@app.route('/prematch/<fixture_id>', methods=['GET'])
def prematch_fixture_detail(fixture_id):
    """Single pre-match fixture details by fixture ID."""
    it, ev = find_ev_by_oi(fixture_id, PREMATCH_DATA)
    if not ev:
        return jsonify({"error": "Fixture not found"}), 404
    sport_id = ev.get("_sportId", "1")
    res = format_prematch_event(it, ev, sport_id)
    if not res:
        return jsonify({"error": "Fixture not found"}), 404
    return pretty_json(res)


# =============================================================================
# DASHBOARD UI (Live + Pre-Match Toggle)
# =============================================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bet365 Live & Pre-Match Hub</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-primary: #0d1117;
      --bg-secondary: #161b22;
      --bg-card: #21262d;
      --bg-card-hover: #292e36;
      --text-main: #f0f6fc;
      --text-muted: #8b949e;
      --accent-green: #238636;
      --accent-green-glow: #2ea043;
      --live-red: #f85149;
      --prematch-blue: #58a6ff;
      --border-color: #30363d;
      --odds-bg: #1c2128;
      --odds-hover: #388bfd33;
      --odds-text: #7ee787;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg-primary);
      color: var(--text-main);
      min-height: 100vh;
      padding-bottom: 40px;
    }
    header {
      background-color: var(--bg-secondary);
      border-bottom: 1px solid var(--border-color);
      padding: 16px 24px;
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(10px);
    }
    .header-container {
      max-width: 1300px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo-badge {
      background: linear-gradient(135deg, #137333, #1e8e3e);
      color: white;
      font-weight: 800;
      font-size: 14px;
      padding: 6px 10px;
      border-radius: 6px;
      letter-spacing: 0.5px;
    }
    .live-dot {
      display: inline-block;
      width: 10px; height: 10px;
      background-color: var(--live-red);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--live-red);
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0% { transform: scale(0.95); opacity: 0.8; }
      50% { transform: scale(1.2); opacity: 1; }
      100% { transform: scale(0.95); opacity: 0.8; }
    }
    .mode-toggle {
      display: flex;
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      overflow: hidden;
    }
    .mode-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 8px 18px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .mode-btn.active {
      background: var(--accent-green);
      color: white;
    }
    .mode-btn:hover:not(.active) {
      color: var(--text-main);
      background: var(--bg-card-hover);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .search-input {
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 14px;
      outline: none;
      width: 200px;
      transition: all 0.2s;
    }
    .search-input:focus {
      border-color: #58a6ff;
      width: 250px;
    }
    .btn {
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
      text-decoration: none;
    }
    .btn:hover {
      background-color: var(--bg-card-hover);
      border-color: #8b949e;
    }
    .btn-green {
      background-color: var(--accent-green);
      border-color: var(--accent-green-glow);
      color: white;
    }
    .btn-green:hover { background-color: var(--accent-green-glow); }
    .container {
      max-width: 1300px;
      margin: 20px auto;
      padding: 0 20px;
    }
    .sports-tabs {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 12px;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--border-color);
    }
    .tab {
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      color: var(--text-muted);
      padding: 8px 16px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      transition: all 0.2s;
    }
    .tab:hover { color: var(--text-main); border-color: #8b949e; }
    .tab.active {
      background-color: #238636;
      border-color: #2ea043;
      color: white;
    }
    .badge-count {
      background-color: rgba(255,255,255,0.2);
      padding: 2px 7px;
      border-radius: 10px;
      font-size: 11px;
    }
    .matches-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 16px;
    }
    .match-card {
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 10px;
      padding: 16px;
      transition: transform 0.15s, border-color 0.15s;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .match-card:hover {
      border-color: #58a6ff;
      transform: translateY(-2px);
    }
    .match-card.prematch { border-left: 3px solid var(--prematch-blue); }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      font-size: 12px;
      color: var(--text-muted);
    }
    .league-name {
      font-weight: 600;
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .clock-badge {
      background-color: rgba(248, 81, 73, 0.15);
      color: var(--live-red);
      border: 1px solid rgba(248, 81, 73, 0.3);
      padding: 3px 8px;
      border-radius: 12px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .schedule-badge {
      background-color: rgba(88, 166, 255, 0.15);
      color: var(--prematch-blue);
      border: 1px solid rgba(88, 166, 255, 0.3);
      padding: 3px 8px;
      border-radius: 12px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      font-weight: 700;
    }
    .status-badge {
      font-size: 11px;
      color: var(--prematch-blue);
      margin-top: -4px;
      margin-bottom: 10px;
      font-weight: 600;
    }
    .score-section {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-bottom: 14px;
    }
    .team-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 15px;
      font-weight: 600;
    }
    .team-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 280px;
    }
    .team-score {
      font-family: 'JetBrains Mono', monospace;
      font-size: 18px;
      font-weight: 700;
      color: #58a6ff;
      min-width: 24px;
      text-align: right;
    }
    .period-badge {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: -4px;
      margin-bottom: 10px;
    }
    .markets-section {
      border-top: 1px solid var(--border-color);
      padding-top: 12px;
      margin-top: auto;
    }
    .market-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 8px;
      font-weight: 700;
    }
    .odds-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .odd-box {
      background-color: var(--odds-bg);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 8px;
      text-align: center;
      transition: all 0.2s;
    }
    .odd-box:hover {
      border-color: #58a6ff;
      background-color: var(--odds-hover);
    }
    .odd-label {
      font-size: 11px;
      color: var(--text-muted);
      display: block;
      margin-bottom: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .odd-val {
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      font-weight: 700;
      color: var(--odds-text);
    }
    .odd-frac {
      font-size: 10px;
      color: var(--text-muted);
      margin-left: 4px;
    }
    .stats-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      background-color: var(--bg-card);
      border-radius: 6px;
      padding: 6px 10px;
      margin-top: 10px;
      font-size: 11px;
      color: var(--text-muted);
    }
    .stat-item { display: inline-flex; align-items: center; gap: 4px; }
    .stat-num { color: var(--text-main); font-weight: 600; }
    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: var(--text-muted);
    }
    .empty-state h3 {
      font-size: 20px;
      margin-bottom: 8px;
      color: var(--text-main);
    }
    .api-links { display: flex; gap: 10px; align-items: center; }
  </style>
</head>
<body>
  <header>
    <div class="header-container">
      <div class="brand">
        <span class="logo-badge">BET365</span>
        <span class="live-dot" id="liveDot"></span>
        <h2 style="font-size: 18px; font-weight: 700;">Live & Pre-Match Hub</h2>
      </div>
      <div class="mode-toggle">
        <button class="mode-btn active" id="btnLive" onclick="setMode('live')">
          <span>🔴 Live</span>
        </button>
        <button class="mode-btn" id="btnPrematch" onclick="setMode('prematch')">
          <span>📅 Pre-Match</span>
        </button>
      </div>
      <div class="actions">
        <input type="text" id="searchBox" class="search-input" placeholder="🔍 Search match, league..." oninput="renderMatches()">
        <button class="btn btn-green" id="autoRefreshBtn" onclick="toggleAutoRefresh()">⚡ Auto-Refresh: ON</button>
        <button class="btn" onclick="fetchMatches()">🔄 Refresh</button>
        <a href="/live" target="_blank" class="btn" id="rawApiLink">📄 Raw JSON</a>
      </div>
    </div>
  </header>

  <div class="container">
    <div class="sports-tabs" id="sportsTabs">
      <button class="tab active" onclick="selectSport('all', this)">
        <span>🌟 All Sports</span>
        <span class="badge-count" id="countAll">0</span>
      </button>
    </div>

    <div class="matches-grid" id="matchesGrid">
      <div class="empty-state">
        <h3>Connecting to Feed...</h3>
        <p>Ensure the Chrome Extension is loaded and Bet365 tab is active.</p>
      </div>
    </div>
  </div>

  <script>
    let allMatches = [];
    let sportsList = [];
    let currentSport = 'all';
    let currentMode = 'live';
    let autoRefresh = true;
    let refreshInterval = null;

    const SPORT_ICONS = {
      '1': '⚽', '18': '🏀', '13': '🎾', '16': '⚾',
      '17': '🏒', '151': '🎮', '3': '🏏', '8': '🏉', '2': '🐎'
    };

    function setMode(mode) {
      currentMode = mode;
      currentSport = 'all';
      document.getElementById('btnLive').classList.toggle('active', mode === 'live');
      document.getElementById('btnPrematch').classList.toggle('active', mode === 'prematch');
      document.getElementById('liveDot').style.display = mode === 'live' ? 'inline-block' : 'none';
      document.getElementById('rawApiLink').href = mode === 'live' ? '/live' : '/prematch';
      fetchMatches();
    }

    async function fetchSports() {
      try {
        const res = await fetch(`/sports?scope=${currentMode}`);
        sportsList = await res.json();
        renderSportsTabs();
      } catch (err) {
        console.error('Error fetching sports:', err);
      }
    }

    async function fetchMatches() {
      try {
        const url = currentSport === 'all'
          ? (currentMode === 'live' ? '/live' : '/prematch')
          : (currentMode === 'live' ? `/live?sport=${currentSport}` : `/prematch?sport=${currentSport}`);
        const res = await fetch(url);
        allMatches = await res.json();
        document.getElementById('countAll').innerText = allMatches.length;
        renderMatches();
        fetchSports();
      } catch (err) {
        console.error('Error fetching matches:', err);
      }
    }

    function renderSportsTabs() {
      const container = document.getElementById('sportsTabs');
      let html = `<button class="tab ${currentSport === 'all' ? 'active' : ''}" onclick="selectSport('all', this)">
        <span>🌟 All Sports</span>
        <span class="badge-count" id="countAll">${allMatches.length}</span>
      </button>`;

      sportsList.forEach(sp => {
        const icon = SPORT_ICONS[sp.id] || '🏆';
        const isActive = currentSport === sp.id ? 'active' : '';
        html += `<button class="tab ${isActive}" onclick="selectSport('${sp.id}', this)">
          <span>${icon} ${sp.name || 'Sport ' + sp.id}</span>
          <span class="badge-count">${sp.count}</span>
        </button>`;
      });

      container.innerHTML = html;
    }

    function selectSport(sportId, btn) {
      currentSport = sportId;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      fetchMatches();
    }

    function toggleAutoRefresh() {
      autoRefresh = !autoRefresh;
      const btn = document.getElementById('autoRefreshBtn');
      if (autoRefresh) {
        btn.innerText = '⚡ Auto-Refresh: ON';
        btn.classList.add('btn-green');
        startTimer();
      } else {
        btn.innerText = '⏸️ Auto-Refresh: OFF';
        btn.classList.remove('btn-green');
        clearInterval(refreshInterval);
      }
    }

    function startTimer() {
      if (refreshInterval) clearInterval(refreshInterval);
      refreshInterval = setInterval(fetchMatches, 2000);
    }

    function renderMatches() {
      const grid = document.getElementById('matchesGrid');
      const search = document.getElementById('searchBox').value.toLowerCase().trim();

      let filtered = allMatches;
      if (currentSport !== 'all') {
        filtered = filtered.filter(m => String(m.sportId) === String(currentSport));
      }
      if (search) {
        filtered = filtered.filter(m => 
          (m.event && m.event.toLowerCase().includes(search)) ||
          (m.league && m.league.toLowerCase().includes(search)) ||
          (m.homeTeam && m.homeTeam.toLowerCase().includes(search)) ||
          (m.awayTeam && m.awayTeam.toLowerCase().includes(search))
        );
      }

      if (filtered.length === 0) {
        grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">
          <h3>No ${currentMode} matches found</h3>
          <p>Make sure you open the Bet365 ${currentMode === 'prematch' ? 'Sports / Competitions (e.g. Football / Basketball)' : 'In-Play'} page in Chrome with the extension active.</p>
        </div>`;
        return;
      }

      let cardsHtml = '';
      filtered.forEach(m => {
        const isPrematch = currentMode === 'prematch' || m.status === 'prematch';
        const icon = SPORT_ICONS[m.sportId] || '🏆';

        let oddsHtml = '';
        if (m.markets && m.markets.length > 0) {
          const mainMarket = m.markets[0];
          const oddsBoxes = (mainMarket.odds || []).map(od => {
            const dec = od.oddsDecimal ? od.oddsDecimal.toFixed(2) : '-';
            const frac = od.oddsFractional ? `(${od.oddsFractional})` : '';
            return `<div class="odd-box">
              <span class="odd-label">${od.name || od.handicap || 'Odd'}</span>
              <span class="odd-val">${dec}</span><span class="odd-frac">${frac}</span>
            </div>`;
          }).join('');

          oddsHtml = `
            <div class="markets-section">
              <div class="market-title">${mainMarket.name || 'Full Time Result'}</div>
              <div class="odds-row">${oddsBoxes}</div>
            </div>
          `;
        }

        if (isPrematch) {
          cardsHtml += `
            <div class="match-card prematch">
              <div>
                <div class="card-header">
                  <span class="league-name" title="${m.league}">${icon} ${m.league || m.sport}</span>
                  <span class="schedule-badge">📅 ${m.scheduledDisplay || 'TBA'}</span>
                </div>
                <div class="score-section">
                  <div class="team-row">
                    <span class="team-name" title="${m.homeTeam || m.event}">${m.homeTeam || m.event}</span>
                    <span class="team-score">-</span>
                  </div>
                  <div class="team-row">
                    <span class="team-name" title="${m.awayTeam}">${m.awayTeam}</span>
                    <span class="team-score">-</span>
                  </div>
                </div>
                <div class="status-badge">⏳ Pre-Match</div>
              </div>
              ${oddsHtml}
            </div>
          `;
        } else {
          const timeDisplay = m.time ? `⏱️ ${m.time}` : (m.period || 'Live');

          let statsHtml = '';
          if (m.stats && Object.keys(m.stats).length > 0) {
            const corners = m.stats.Corner ? `🚩 Corners: <span class="stat-num">${m.stats.Corner.home ?? 0}-${m.stats.Corner.away ?? 0}</span>` : '';
            const cards = m.stats.YellowCard ? `🟨 Cards: <span class="stat-num">${m.stats.YellowCard.home ?? 0}-${m.stats.YellowCard.away ?? 0}</span>` : '';
            const redCards = m.stats.RedCard ? `🟥 Red: <span class="stat-num">${m.stats.RedCard.home ?? 0}-${m.stats.RedCard.away ?? 0}</span>` : '';
            if (corners || cards || redCards) {
              statsHtml = `<div class="stats-bar">${corners} ${cards} ${redCards}</div>`;
            }
          }

          cardsHtml += `
            <div class="match-card">
              <div>
                <div class="card-header">
                  <span class="league-name" title="${m.league}">${icon} ${m.league || m.sport}</span>
                  <span class="clock-badge">${timeDisplay}</span>
                </div>
                <div class="score-section">
                  <div class="team-row">
                    <span class="team-name" title="${m.homeTeam || m.event}">${m.homeTeam || m.event}</span>
                    <span class="team-score">${m.homeScore !== null ? m.homeScore : '-'}</span>
                  </div>
                  <div class="team-row">
                    <span class="team-name" title="${m.awayTeam}">${m.awayTeam}</span>
                    <span class="team-score">${m.awayScore !== null ? m.awayScore : '-'}</span>
                  </div>
                </div>
                ${m.period ? `<div class="period-badge">📍 ${m.period}</div>` : ''}
                ${statsHtml}
              </div>
              ${oddsHtml}
            </div>
          `;
        }
      });

      grid.innerHTML = cardsHtml;
    }

    fetchMatches();
    startTimer();
  </script>
</body>
</html>
"""


@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
def dashboard():
    """Serve modern responsive live + pre-match scoreboard dashboard."""
    return DASHBOARD_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}


if __name__ == '__main__':
    CORS(app)
    app.run(host='0.0.0.0', port=8485, threaded=True, debug=False)