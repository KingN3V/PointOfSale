import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


def send_password_reset_email(to_email: str, code: str) -> None:
    """Sends the reset code by email. Raises if the SMTP send fails —
    callers decide how to surface that to the client.
    """
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD):
        raise RuntimeError(
            "SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD must be set in .env "
            "before password reset emails can be sent."
        )

    message = EmailMessage()
    message["Subject"] = "Your POS password reset code"
    message["From"] = SMTP_USERNAME
    message["To"] = to_email
    message.set_content(
        f"Your password reset code is: {code}\n\n"
        "Enter this code in the app to set a new password. "
        "It expires in 15 minutes.\n\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)