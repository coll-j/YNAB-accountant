from tests.email_tests import test_email_fetch, test_email_parsing

if __name__ == "__main__":
    print("Running email fetch test...")
    emails = test_email_fetch()
    print("Running email parsing test...")
    test_email_parsing(emails)


