import yaml
from agents.email_agent import EmailAgent

def test_email_fetch():
    cfg = yaml.safe_load(open('config.yaml'))
    agent = EmailAgent(
        cfg['gmail']['credentials_file'],
        cfg['gmail']['token_file'],
        cfg['gmail']['trigger_subject_keyword'],
    )
    emails = agent.fetch_new_payment_emails()
    print(f'Found {len(emails)} unread payment emails')
    for e in emails:
        print(f'  [{e["id"]}] {e["subject"]}')
        print(f'  Body preview: {e["body"][:200]}')
        print()

    return emails

def test_email_parsing(emails):
    from core.email_parser import EmailParser
    parser = EmailParser()

    for email in emails:
        print(f'Parsing email: {email["subject"]}')
        parsed = parser.parse(email["body"], email["subject"], email["id"])
        print(f'Parsed result: {parsed}')
        print()