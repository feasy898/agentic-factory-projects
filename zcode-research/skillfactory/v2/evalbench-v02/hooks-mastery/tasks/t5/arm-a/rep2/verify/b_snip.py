import sys, json
def all_tests_passed(): return False

# ---- Version B core (as given by the colleague) ----
if not all_tests_passed():
    output = {"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}
    print(json.dumps(output))
    sys.exit(0)
