import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core.config import settings


class EmailService:
    """Service for sending emails using SMTP"""

    @staticmethod
    def send_email(
        to_emails: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> dict:
        """
        Send an email using SMTP.

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body

        Returns:
            dict: Status message

        Raises:
            Exception: If email sending fails
        """
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            raise ValueError(
                "Email credentials not configured. Please set SMTP_USER and SMTP_PASSWORD in .env"
            )

        # Create message
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM or settings.SMTP_USER}>"
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = subject

        # Attach plain text body
        msg.attach(MIMEText(body, "plain"))

        # Attach HTML body if provided
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        try:
            # Connect to SMTP server
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()  # Secure the connection
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            return {
                "success": True,
                "message": f"Email sent successfully to {len(to_emails)} recipient(s)",
                "recipients": to_emails,
            }

        except smtplib.SMTPAuthenticationError:
            raise Exception(
                "SMTP Authentication failed. Please check your email credentials."
            ) from None
        except smtplib.SMTPException as e:
            raise Exception(f"SMTP error occurred: {e!s}") from e
        except Exception as e:
            raise Exception(f"Failed to send email: {e!s}") from e


# Create a singleton instance
email_service = EmailService()
