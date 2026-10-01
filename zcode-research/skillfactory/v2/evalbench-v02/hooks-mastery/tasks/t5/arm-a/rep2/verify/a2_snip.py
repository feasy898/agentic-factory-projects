import sys
def all_tests_passed(): return False

# ---- Version A minimal fix: exit code 2 + stderr (blocking error) ----
if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.", file=sys.stderr)
    sys.exit(2)
