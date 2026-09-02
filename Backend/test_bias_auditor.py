"""
test_bias_auditor.py

Hand-written validation set for the Bias Auditor. No ground-truth
dataset exists for "is this justification biased" — so this is our
own defensible test harness, per Phase 3 guide Section 3.
"""

from dotenv import load_dotenv
load_dotenv()

from agents.bias_auditor import audit_screening

TEST_CASES = [
    # Obviously biased
    {
        "justification": "Scored lower primarily due to a 2-year gap in employment history.",
        "expected_flag": "review",
    },
    {
        "justification": "Scored higher partly due to attending a well-known IIT, despite limited hands-on project experience.",
        "expected_flag": "high-concern",
    },
    {
        "justification": "Scored lower because the graduation year suggests the candidate may be less adaptable to newer technologies.",
        "expected_flag": "high-concern",
    },

    # Obviously clean
    {
        "justification": "Scored lower due to lacking the required 3 years of experience with distributed systems, as specified in the JD.",
        "expected_flag": "none",
    },
    {
        "justification": "Scored well due to demonstrated proficiency in Python and AWS, both listed as must-have skills.",
        "expected_flag": "none",
    },
    {
        "justification": "Scored lower because the resume shows no mention of REST API design or PostgreSQL, both required skills for this role.",
        "expected_flag": "none",
    },

    # Subtle / borderline
    {
        "justification": "Scored lower due to lack of full-time professional experience, despite strong project work and internships.",
        "expected_flag": "review",
    },
    {
        "justification": "Scored slightly lower than expected because the candidate's experience level appears higher than the mid-level role requires.",
        "expected_flag": "review",
    },
    {
        "justification": "Scored lower partly due to a non-traditional career path, though the candidate's technical skills match the JD closely.",
        "expected_flag": "review",
    },
    {
        "justification": "Scored well because the candidate demonstrates strong ownership, citing a specific project where they designed and deployed a microservice independently.",
        "expected_flag": "none",
    },
]

def validate_auditor(test_cases: list[dict]) -> float:
    correct = 0
    for case in test_cases:
        result = audit_screening(
            structured_jd={"must_have_skills": ["Python", "FastAPI", "PostgreSQL","AWS"]},
            resume_text="",
            score=50,
            justification=case["justification"],
        )
        if result["flag_level"] == case["expected_flag"]:
            correct += 1
        else:
            print(f"MISMATCH: expected {case['expected_flag']}, got {result['flag_level']}")
            print(f"  Justification: {case['justification']}")
            print(f"  Auditor reasoning: {result['reasoning']}")
            print()

    accuracy = correct / len(test_cases)
    print(f"\nAccuracy: {correct}/{len(test_cases)} ({accuracy:.0%})")
    return accuracy


if __name__ == "__main__":
    validate_auditor(TEST_CASES)