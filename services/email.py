"""Email service — sends transactional emails via SMTP."""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _send_smtp(to_email: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(msg["From"], to_email, msg.as_string())


async def send_hire_congratulation_email(
    to_email: str,
    applicant_name: str,
    position_label: str,
) -> bool:
    """Send a hire congratulation email to a new employee. Returns True on success."""
    if not _is_configured():
        logger.warning("SMTP not configured — hire email not sent to %s", to_email)
        return False

    subject = "You're Hired! — Veteran Lawns & Landscapes"
    html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f3ee;font-family:Georgia,serif;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:40px 16px;">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
      <tr>
        <td style="background:linear-gradient(135deg,#1b3a2f,#3a6642);padding:36px 40px;text-align:center;">
          <div style="font-size:36px;margin-bottom:8px;">&#127881;</div>
          <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Congratulations, {applicant_name}!</h1>
          <p style="margin:8px 0 0;color:rgba(255,255,255,0.8);font-size:15px;">Welcome to the Veteran Lawns &amp; Landscapes team</p>
        </td>
      </tr>
      <tr>
        <td style="padding:40px;">
          <p style="margin:0 0 16px;color:#2d2d2d;font-size:16px;">We're thrilled to offer you a position on our <strong>{position_label}</strong>.</p>
          <p style="margin:0 0 24px;color:#555;font-size:15px;line-height:1.6;">Our team will be in touch shortly with onboarding details, your start date, and next steps. We look forward to having you with us!</p>
          <div style="background:#f5f3ee;border-radius:10px;padding:20px 24px;text-align:center;">
            <div style="font-size:32px;margin-bottom:8px;">&#9874;</div>
            <div style="font-size:15px;color:#1b3a2f;font-weight:700;">Veteran Lawns &amp; Landscapes</div>
            <div style="font-size:13px;color:#888;margin-top:4px;">Proudly serving Harford County, MD</div>
          </div>
        </td>
      </tr>
      <tr>
        <td style="background:#f5f3ee;padding:20px 40px;text-align:center;border-top:1px solid #e8e4dd;">
          <p style="margin:0;color:#aaa;font-size:12px;">Veteran Lawns &amp; Landscapes · Harford County, MD</p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""

    try:
        await asyncio.to_thread(_send_smtp, to_email, subject, html)
        logger.info("Hire congratulation email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send hire email to %s", to_email)
        return False


async def send_payment_link_email(
    to_email: str,
    customer_name: str,
    checkout_url: str,
    monthly_quote: float,
) -> bool:
    """Send a payment link email to a customer. Returns True on success."""
    if not _is_configured():
        logger.warning("SMTP not configured — payment link email not sent to %s", to_email)
        return False

    subject = "Your Veteran Lawns & Landscapes Quote — Ready to Activate"
    html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f3ee;font-family:Georgia,serif;">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:40px 16px;">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

      <!-- Header -->
      <tr>
        <td style="background:linear-gradient(135deg,#1b3a2f,#3a6642);padding:36px 40px;text-align:center;">
          <div style="font-size:28px;margin-bottom:6px;">&#9874;</div>
          <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:0.5px;">
            Veteran Lawns &amp; Landscapes
          </h1>
          <p style="margin:6px 0 0;color:rgba(255,255,255,0.75);font-size:14px;">
            Harford County, MD
          </p>
        </td>
      </tr>

      <!-- Body -->
      <tr>
        <td style="padding:40px;">
          <p style="margin:0 0 16px;color:#2d2d2d;font-size:16px;">
            Hi <strong>{customer_name}</strong>,
          </p>
          <p style="margin:0 0 24px;color:#555;font-size:15px;line-height:1.6;">
            Great news — your lawn care quote has been reviewed and approved.
            You can now activate your monthly service by completing your secure payment below.
          </p>

          <!-- Quote amount -->
          <div style="background:#f5f3ee;border-radius:10px;padding:20px 24px;margin:0 0 28px;text-align:center;">
            <div style="font-size:13px;color:#888;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">
              Monthly Service Rate
            </div>
            <div style="font-size:36px;font-weight:800;color:#1b3a2f;">
              ${monthly_quote:.2f}
            </div>
            <div style="font-size:13px;color:#888;">per month · billed monthly · cancel anytime</div>
          </div>

          <!-- CTA Button -->
          <div style="text-align:center;margin:0 0 28px;">
            <a href="{checkout_url}"
               style="display:inline-block;background:#1b3a2f;color:#ffffff;text-decoration:none;
                      padding:16px 40px;border-radius:8px;font-size:16px;font-weight:700;
                      letter-spacing:0.3px;">
              &#128274; Activate My Service
            </a>
          </div>

          <p style="margin:0 0 8px;color:#999;font-size:13px;text-align:center;">
            Powered by Stripe — your payment info is never stored on our servers.
          </p>
          <p style="margin:0;color:#bbb;font-size:12px;text-align:center;">
            This link expires in 24 hours. If you have questions, reply to this email
            or call us during business hours.
          </p>
        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="background:#f5f3ee;padding:20px 40px;text-align:center;
                   border-top:1px solid #e8e4dd;">
          <p style="margin:0;color:#aaa;font-size:12px;">
            Veteran Lawns &amp; Landscapes · Harford County, MD<br>
            Proudly serving veterans and their neighbors.
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""

    try:
        await asyncio.to_thread(_send_smtp, to_email, subject, html)
        logger.info("Payment link email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send payment link email to %s", to_email)
        return False
