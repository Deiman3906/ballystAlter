import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def add_subscriber(user_id: int, username: str = "", first_name: str = "", access_hash: int = None):
    data = {
        "user_id":    user_id,
        "username":   username,
        "first_name": first_name,
        "active":     True,
    }
    if access_hash is not None:
        data["access_hash"] = access_hash
    sb.table("subscribers").upsert(data, on_conflict="user_id").execute()


def remove_subscriber(user_id: int):
    sb.table("subscribers").update({"active": False}) \
      .eq("user_id", user_id).execute()


def get_subscribers() -> list[int]:
    res = sb.table("subscribers") \
            .select("user_id") \
            .eq("active", True) \
            .execute()
    return [row["user_id"] for row in res.data]


def get_subscribers_full() -> list[dict]:
    res = sb.table("subscribers") \
            .select("user_id, access_hash, username") \
            .eq("active", True) \
            .execute()
    return res.data


def log_alert(source: str, message_text: str, notified: int) -> int:
    res = sb.table("alerts").insert({
        "source":       source,
        "message_text": message_text,
        "notified":     notified,
    }).execute()
    return res.data[0]["id"]


def log_call(alert_id: int, user_id: int, status: str = "success"):
    sb.table("call_logs").insert({
        "alert_id": alert_id,
        "user_id":  user_id,
        "status":   status,
    }).execute()

