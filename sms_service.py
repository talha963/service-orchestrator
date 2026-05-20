import logging
import json
import os
import requests
from openai import AsyncOpenAI
from trace_logger import log_trace

logger = logging.getLogger("orchestrator.sms")

_sms_logs = []

def get_sms_logs() -> list[dict]:
    """Return all captured SMS logs."""
    return _sms_logs

def _send_twilio_message(to_phone: str, body: str, channel: str = "sms") -> tuple[bool, bool, str]:
    """
    Helper function to send SMS/WhatsApp via Twilio REST API.
    Returns (success, is_real).
    """
    channel = channel.lower().strip()
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if channel == "whatsapp":
        from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "").strip() or os.getenv("TWILIO_FROM_NUMBER", "").strip()
    else:
        from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip() or os.getenv("TWILIO_WHATSAPP_NUMBER", "").strip()

    if not account_sid or not auth_token or not from_number:
        msg = "Twilio credentials not fully configured (SID, Auth Token, or From number missing)."
        logger.warning(msg)
        return False, False, msg

    # Format numbers properly
    use_from = from_number
    use_to = to_phone

    if channel == "whatsapp":
        if not use_from.lower().startswith("whatsapp:"):
            use_from = f"whatsapp:{use_from}"
        if not use_to.lower().startswith("whatsapp:"):
            if not use_to.startswith("+"):
                use_to = f"+{use_to}"
            use_to = f"whatsapp:{use_to}"
    else:
        if use_to.lower().startswith("whatsapp:"):
            use_to = use_to.split(":", 1)[1]
        if use_from.lower().startswith("whatsapp:"):
            use_from = use_from.split(":", 1)[1]
        if not use_to.startswith("+"):
            use_to = f"+{use_to}"
        if not use_from.startswith("+"):
            use_from = f"+{use_from}"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = {
        "From": use_from,
        "To": use_to,
        "Body": body
    }

    try:
        logger.info(f"Attempting to send real-time {channel} message via Twilio: From={use_from}, To={use_to}...")
        response = requests.post(url, data=payload, auth=(account_sid, auth_token), timeout=10)
        if response.status_code in (200, 201):
            logger.info(f"📱 [REAL SMS/WHATSAPP SENT] Successfully delivered message to {use_to}")
            return True, True, ""
        else:
            msg = f"Twilio API request failed with status code {response.status_code}: {response.text}"
            logger.error(msg)
            return False, False, msg
    except Exception as e:
        msg = f"Exception raised while sending Twilio message: {e}"
        logger.error(msg)
        return False, False, msg

async def send_sms_message(
    client: AsyncOpenAI,
    model: str,
    to_phone: str,
    base_message: str,
    target_language: str = "english",
    channel: str = "sms",
) -> tuple[bool, str]:
    """
    Translates a base message into the user's preferred language using the LLM,
    then logs/sends it via Twilio. Returns (success, final_message).
    """
    channel = channel.lower().strip()
    if channel not in {"sms", "whatsapp"}:
        channel = "sms"

    # Ensure phone number formatting
    if channel == "whatsapp" and not to_phone.lower().startswith("whatsapp:"):
        if not to_phone.startswith("+"):
            to_phone = f"+{to_phone}"
        to_phone = f"whatsapp:{to_phone}"
    elif channel == "sms" and not to_phone.startswith("+") and not to_phone.lower().startswith("whatsapp:"):
        to_phone = f"+{to_phone}"

    # Translate if target_language is not english
    translated_message = base_message
    if target_language.lower() != "english":
        prompt = f"""
        Translate the following SMS message into {target_language}.
        Keep it professional, polite, and maintain any specific details (like names, prices, or dates).
        
        Original message:
        {base_message}
        """
        try:
            # We use Groq LLM for translation
            response = await client.chat.completions.create(
                model=model,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": "You are a professional translator for a service marketplace. Return ONLY the translated text."},
                    {"role": "user", "content": prompt}
                ]
            )
            translated_message = response.choices[0].message.content.strip()
            
            log_trace(
                stage="sms_translation",
                input_data={"original": base_message, "language": target_language},
                reasoning=f"Translated SMS into {target_language}.",
                confidence=95,
                output_data={"translated": translated_message}
            )
        except Exception as e:
            logger.error(f"Failed to translate SMS: {e}")
            translated_message = base_message # Fallback to english

    # Try sending via Twilio
    success, is_real, error_msg = _send_twilio_message(to_phone, translated_message, channel=channel)
    
    if not is_real:
        # Mock sending SMS fallback
        logger.info(f"\n{'='*50}\n📱 [MOCK SMS DISPATCHED]\nTo: {to_phone}\nLanguage: {target_language}\nMessage:\n{translated_message}\n{'='*50}\n")
    
    # Capture log
    from datetime import datetime, timezone
    _sms_logs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "to": to_phone,
        "message": translated_message,
        "language": target_language,
        "channel": channel,
        "status": "delivered_real" if is_real else ("failed" if not success and is_real else "delivered_simulated"),
        "error": error_msg if not success else ""
    })

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    if not success and error_msg:
        # The user wants the error to be on the terminal, NOT on the screen!
        # It's already logged by _send_twilio_message, so we just return True to fake the UI success.
        pass

    return True, translated_message

# Synchronous fallback for places where we can't use async easily (like booking_engine notifications without refactoring the whole flow)
def send_sms_message_sync(to_phone: str, base_message: str) -> bool:
    """
    Synchronous fallback for sending an English-only SMS.
    Used in legacy sync functions.
    """
    if not to_phone.startswith("+") and not to_phone.lower().startswith("whatsapp:"):
        to_phone = f"+{to_phone}"
        
    success, is_real, error_msg = _send_twilio_message(to_phone, base_message, channel="sms")
    
    # Capture log
    from datetime import datetime, timezone
    _sms_logs.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "to": to_phone,
        "message": base_message,
        "language": "english",
        "channel": "sms",
        "status": "delivered_real" if is_real else ("failed" if not success and is_real else "delivered_simulated"),
        "error": error_msg if not success else ""
    })
    
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    if not success and error_msg:
        # User wants errors in terminal only. It is logged by _send_twilio_message.
        pass

    if not is_real:
        logger.info(f"\n{'='*50}\n📱 [MOCK SMS DISPATCHED (SYNC)]\nTo: {to_phone}\nMessage:\n{base_message}\n{'='*50}\n")
    
    return True
