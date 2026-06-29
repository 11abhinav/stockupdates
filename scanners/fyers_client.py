import os
import logging
import base64
import requests
import urllib.parse
from datetime import datetime
import pandas as pd

try:
    import pyotp
except ImportError:
    pyotp = None

try:
    from fyers_apiv3 import fyersModel
except ImportError:
    fyersModel = None

log = logging.getLogger("scanners.fyers")

_cached_fyers_instance = None
_token_expiry_date = None

def get_fyers_instance():
    global _cached_fyers_instance, _token_expiry_date
    
    client_id = os.environ.get("FYERS_CLIENT_ID")
    if not client_id or not fyersModel:
        return None
        
    now_date = datetime.now().date()
    if _cached_fyers_instance and _token_expiry_date == now_date:
        return _cached_fyers_instance
        
    try:
        secret_key = os.environ.get("FYERS_SECRET_KEY")
        totp_secret = os.environ.get("FYERS_TOTP_SECRET")
        pin = os.environ.get("FYERS_PIN")
        user_id = os.environ.get("FYERS_USER_ID")
        redirect_uri = os.environ.get("FYERS_REDIRECT_URI", "https://google.com")
        
        if not all([secret_key, totp_secret, pin, user_id]) or not pyotp:
            log.warning("Fyers API enabled but missing TOTP/PIN/UserID or pyotp package in environment.")
            return None
            
        # Step 1: Send Login OTP Request
        log.info("Fyers login Step 1: Sending login OTP request...")
        session = requests.Session()
        payload = {"fy_id": base64.b64encode(f"{user_id}".encode()).decode(), "app_id": "2"}
        res = session.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2", json=payload).json()
        log.info(f"Step 1 response: {res}")
        if 'request_key' not in res:
            log.error(f"Fyers Step 1 failed: {res}")
            return None
        request_key = res["request_key"]
        
        # Step 2: Verify TOTP
        log.info("Fyers login Step 2: Verifying TOTP...")
        totp = pyotp.TOTP(totp_secret).now()
        payload2 = {"request_key": request_key, "otp": totp}
        res2 = session.post("https://api-t2.fyers.in/vagator/v2/verify_otp", json=payload2).json()
        log.info(f"Step 2 response: {res2}")
        if 'request_key' not in res2:
            log.error(f"Fyers Step 2 TOTP verification failed: {res2}")
            return None
        request_key = res2["request_key"]
        
        # Step 3: Verify PIN
        log.info("Fyers login Step 3: Verifying PIN...")
        payload3 = {"request_key": request_key, "identity_type": "pin", "identifier": base64.b64encode(f"{pin}".encode()).decode()}
        res3 = session.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2", json=payload3).json()
        log.info(f"Step 3 response: {res3}")
        if 'data' not in res3 or 'access_token' not in res3.get('data', {}):
            log.error(f"Fyers Step 3 PIN verification failed: {res3}")
            return None
        auth_token = res3["data"]["access_token"]
        
        # Step 4: Get Auth Code
        log.info("Fyers login Step 4: Getting auth code...")
        headers = {"Authorization": f"Bearer {auth_token}"}
        payload4 = {
            "fyers_id": user_id,
            "app_id": client_id[:-4],
            "redirect_uri": redirect_uri,
            "appType": "100",
            "code_challenge": "",
            "state": "abcdefg",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True
        }
        res4 = session.post("https://api-t1.fyers.in/api/v3/token", json=payload4, headers=headers).json()
        log.info(f"Step 4 response: {res4}")
        if 'Url' not in res4:
            log.error(f"Fyers Step 4 auth code failed: {res4}")
            return None
        
        parsed = urllib.parse.urlparse(res4['Url'])
        auth_code = urllib.parse.parse_qs(parsed.query)['auth_code'][0]
        
        # Step 5: Get Access Token
        log.info("Fyers login Step 5: Generating access token...")
        sess_model = fyersModel.SessionModel(
            client_id=client_id,
            secret_key=secret_key,
            redirect_uri=redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        sess_model.set_token(auth_code)
        response = sess_model.generate_token()
        log.info(f"Step 5 response keys: {list(response.keys()) if isinstance(response, dict) else response}")
        if 'access_token' not in response:
            log.error(f"Fyers Step 5 token generation failed: {response}")
            return None
        access_token = response["access_token"]
        
        # Initialize Fyers Model
        fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")
        _cached_fyers_instance = fyers
        _token_expiry_date = now_date
        log.info("Fyers headless login successful, token generated.")
        return fyers
        
    except Exception as e:
        log.error(f"Fyers headless login failed at unexpected point: {e}", exc_info=True)
        return None

def get_fyers_history(symbol, resolution, days=5, bse_code=None):
    fyers = get_fyers_instance()
    if not fyers:
        return None
        
    from datetime import timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Map typical resolutions (15m -> 15, 5m -> 5, 1d -> D)
    if resolution.endswith('m'):
        res_code = resolution[:-1]
    elif resolution.endswith('d'):
        res_code = "D"
    else:
        res_code = resolution
        
    def _fetch_for_fyers_symbol(fsym):
        import time
        data = {
            "symbol": fsym,
            "resolution": str(res_code),
            "date_format": "1",
            "range_from": start_date.strftime("%Y-%m-%d"),
            "range_to": end_date.strftime("%Y-%m-%d"),
            "cont_flag": "1"
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = fyers.history(data=data)
                if res.get('s') == 'ok' and res.get('candles'):
                    candles = res['candles']
                    df = pd.DataFrame(candles, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
                    df.set_index('timestamp', inplace=True)
                    return df
                elif res.get('s') == 'error':
                    code = res.get('code')
                    if code == 429:
                        sleep_time = (attempt + 1) * 3  # Backoff: 3s, 6s, 9s
                        log.warning(f"Fyers rate limit (429) for {fsym}. Retrying in {sleep_time}s (Attempt {attempt+1}/{max_retries})")
                        time.sleep(sleep_time)
                        continue
                    else:
                        log.error(f"Fyers API error for {fsym}: code={code}, message={res.get('message')}, full_response={res}")
                        return None
            except Exception as e:
                log.error(f"Error fetching Fyers data for {fsym}: {e}")
                return None
                
        return None

    # 1. Try NSE
    df = _fetch_for_fyers_symbol(f"NSE:{symbol}-EQ")
    if df is not None:
        return df
        
    # 2. Fallback to BSE using bse_code if provided
    bse_groups = ['A', 'B', 'M', 'X', 'T']
    if bse_code:
        for grp in bse_groups:
            df = _fetch_for_fyers_symbol(f"BSE:{bse_code}-{grp}")
            if df is not None:
                return df
            
    # 3. Fallback to BSE using symbol name
    for grp in bse_groups:
        df = _fetch_for_fyers_symbol(f"BSE:{symbol}-{grp}")
        if df is not None:
            return df
        
    log.debug(f"Fyers history returned empty or failed for {symbol} on all NSE/BSE variants")
    return None
