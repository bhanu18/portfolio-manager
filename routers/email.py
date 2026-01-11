from fastapi import APIRouter, HTTPException, status
from models.email import EmailRequest, EmailResponse
from service.email import email_service

router = APIRouter(prefix="/email", tags=["Email"])


@router.post("/sendemail", response_model=EmailResponse, status_code=status.HTTP_200_OK)
async def send_email(email_data: EmailRequest):
    """
    Send an email to one or more recipients.

    - **to**: List of recipient email addresses
    - **subject**: Email subject line
    - **body**: Plain text email body
    - **html_body**: Optional HTML formatted email body

    Example usage from your frontend:
    ```javascript
    fetch('http://your-api-url/email/sendemail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            to: ['user@example.com'],
            subject: 'Portfolio Update',
            body: 'Your portfolio performance...',
            html_body: '<h1>Portfolio Update</h1><p>Your portfolio performance...</p>'
        })
    })
    ```

    **Note:** Make sure to configure SMTP settings in your .env file:
    - SMTP_HOST (default: smtp.gmail.com)
    - SMTP_PORT (default: 587)
    - SMTP_USER (your email address)
    - SMTP_PASSWORD (your email password or app password)
    - EMAIL_FROM (optional, defaults to SMTP_USER)
    """
    try:
        result = email_service.send_email(
            to_emails=email_data.to,
            subject=email_data.subject,
            body=email_data.body,
            html_body=email_data.html_body,
        )
        return EmailResponse(**result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send email: {str(e)}",
        )
