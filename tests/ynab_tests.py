import ynab
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper
from ynab.models.save_transactions_response import SaveTransactionsResponse
import os

def create_transaction():
    # Configure Bearer authorization: bearer
    configuration = ynab.Configuration(
        access_token = os.environ["YNAB_ACCESS_TOKEN"]
    )

    # Enter a context with an instance of the API client
    with ynab.ApiClient(configuration) as api_client:
        # Create an instance of the API class
        api_instance = ynab.TransactionsApi(api_client)
        plan_id = 'plan_id_example' # str | The id of the plan. \"last-used\" can be used to specify the last used plan and \"default\" can be used if default plan selection is enabled (see: https://api.ynab.com/#oauth-default-plan).
        data = ynab.PostTransactionsWrapper() # PostTransactionsWrapper | The transaction or transactions to create.  To create a single transaction you can specify a value for the `transaction` object and to create multiple transactions you can specify an array of `transactions`.  It is expected that you will only provide a value for one of these objects.

        try:
            # Create a single transaction or multiple transactions
            api_response = api_instance.create_transaction(plan_id, data)
            print("The response of TransactionsApi->create_transaction:\n")
            print(api_response)
        except Exception as e:
            print("Exception when calling TransactionsApi->create_transaction: %s\n" % e)