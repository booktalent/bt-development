"""Directly test is_channel_muted + notification_service.dispatch mute short-circuit."""
import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")
os.chdir("/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from routes.iter92 import is_channel_muted
from notification_service import dispatch


async def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    priya = await db.users.find_one({"email": "priya@booktalent.com"}, {"id": 1, "_id": 0, "notification_preferences": 1})
    assert priya, "Priya user not found"
    uid = priya["id"]
    print("Priya prefs:", priya.get("notification_preferences"))

    m1 = await is_channel_muted(db, user_id=uid, event="marketing.digest", channel="whatsapp")
    m2 = await is_channel_muted(db, user_id=uid, event="booking.confirmed", channel="whatsapp")
    print(f"marketing.digest+whatsapp muted={m1} (expect True)")
    print(f"booking.confirmed+whatsapp muted={m2} (expect False - force_on)")
    assert m1 is True, "marketing.digest whatsapp should be muted"
    assert m2 is False, "booking.confirmed should never be muted (force_on)"

    # Dispatch and verify muted_by_user status
    result = await dispatch(db, user_id=uid, event="marketing.digest",
                            channels=["in_app", "whatsapp"], ctx={"test": True})
    print("Dispatch result:", result)
    wa = result["results"].get("whatsapp")
    assert wa and wa.get("status") == "muted_by_user", f"Expected muted_by_user, got {wa}"
    print("PASS: dispatch respects mutes")


asyncio.run(main())
