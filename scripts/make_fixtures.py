"""
scripts/make_fixtures.py

Generates synthetic candidate fixtures for the Genericity Suite (PRD §13.2, §33.9).

Candidates:
  A: Software Engineer (Mid, US remote, tools & languages)
  B: Marketing Manager (Senior, EU hybrid, 2 languages, campaigns & platforms)
  C: Mechanical Engineer (Early career, PE registration, CAD, Japanese non-Latin)
  D: Registered Nurse (Mid, mandatory RN state license #RN-849201, shift work, on-site)

All data is 100% synthetic, invented, and contains zero real candidate details.
"""
from __future__ import annotations

import json
from pathlib import Path
import yaml

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "candidates"


CANDIDATE_A = {
    "profile": {
        "full_name": "Alex Chen (Synthetic)",
        "email": "alex.synthetic@test-candidate-a.org",
        "phone": "+1-555-0101",
        "location": "Seattle, WA, USA",
        "work_mode": "remote",
        "title": "Software Engineer",
        "seniority": "mid",
        "skills": ["Python", "TypeScript", "FastAPI", "PostgreSQL", "Docker", "AWS"],
        "education": "BS Computer Science, State University, GPA 3.8",
        "credentials": [],
        "min_salary": 120000,
        "currency": "USD",
        "requires_sponsorship": False,
    },
    "facts": [
        {"key": "personal.name.full", "value": "Alex Chen (Synthetic)", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.contact.email", "value": "alex.synthetic@test-candidate-a.org", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.location.city", "value": "Seattle", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "preferences.work_mode", "value": "remote", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "skill.python.experience", "value": "5 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "skill.docker.experience", "value": "3 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "compensation.minimum_base", "value": "120000", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "authorization.work_eligible", "value": "True", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
    ],
    "cv_v1": "ALEX CHEN (Synthetic)\nEmail: alex.synthetic@test-candidate-a.org | Phone: +1-555-0101 | Seattle, WA\n\nPROFESSIONAL SUMMARY\nSoftware engineer with 5 years experience in Python, FastAPI, Docker, and PostgreSQL.\n\nEXPERIENCE\nSoftware Engineer | CloudScale Inc | 2021 - Present\n- Built microservices using Python, FastAPI, PostgreSQL.\n- Automated CI/CD pipelines with Docker and AWS.\n\nEDUCATION\nBS Computer Science, GPA 3.8 | 2017 - 2021\n",
    "cv_v2": "ALEX CHEN (Synthetic)\nEmail: alex.synthetic@test-candidate-a.org | Phone: +1-555-0101 | Seattle, WA\n\nPROFESSIONAL SUMMARY\nSenior Software Engineer with 6 years experience in Python, FastAPI, Docker, and PostgreSQL.\n\nEXPERIENCE\nSenior Software Engineer | CloudScale Inc | 2021 - Present\n- Led development of distributed data systems.\n\nEDUCATION\nBS Computer Science, GPA 3.8 | 2017 - 2021\n",
    "interview_answers": {
        "preferences.work_mode": "remote",
        "compensation.minimum_base": "120000",
        "authorization.requires_sponsorship": "False",
    },
    "jobs": {
        "strong_match": {
            "id": "job-a-strong",
            "title": "Senior Python Backend Engineer",
            "company": "Apex Distributed Systems",
            "location": "Remote",
            "remote_ok": True,
            "min_salary": 130000,
            "required_skills": ["Python", "Docker", "PostgreSQL"],
            "required_credentials": [],
        },
        "weak_match": {
            "id": "job-a-weak",
            "title": "Junior Java Developer",
            "company": "Legacy Corp",
            "location": "Remote",
            "remote_ok": True,
            "min_salary": 80000,
            "required_skills": ["Java", "Spring Boot", "Oracle SQL"],
            "required_credentials": [],
        },
        "gate_fail_location": {
            "id": "job-a-location-fail",
            "title": "Staff Python Engineer (On-Site Only)",
            "company": "SecureDefense Labs",
            "location": "Washington, DC (On-site required)",
            "remote_ok": False,
            "min_salary": 150000,
            "required_skills": ["Python", "PostgreSQL"],
            "required_credentials": [],
        },
        "ambiguous": {
            "id": "job-a-ambiguous",
            "title": "DevOps / Reliability Engineer",
            "company": "InfraCorp",
            "location": "Remote",
            "remote_ok": True,
            "min_salary": 125000,
            "required_skills": ["Docker", "AWS", "Go"],
            "required_credentials": [],
        },
    },
    "expected_matches": {
        "ranking_order": ["job-a-strong", "job-a-ambiguous", "job-a-weak"],
        "gate_failures": {"job-a-location-fail": "location_mismatch"},
    },
}


CANDIDATE_B = {
    "profile": {
        "full_name": "Claire Dupont (Synthetic)",
        "email": "claire.synthetic@test-candidate-b.eu",
        "phone": "+33-1-555-0202",
        "location": "Paris, France",
        "work_mode": "hybrid",
        "title": "Marketing Manager",
        "seniority": "senior",
        "skills": ["HubSpot", "Google Analytics", "SEO", "Content Strategy", "Brand Campaigns"],
        "education": "BA Communications, First Class Honours, University of Edinburgh",
        "credentials": [],
        "min_salary": 75000,
        "currency": "EUR",
        "requires_sponsorship": False,
    },
    "facts": [
        {"key": "personal.name.full", "value": "Claire Dupont (Synthetic)", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.contact.email", "value": "claire.synthetic@test-candidate-b.eu", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.location.city", "value": "Paris", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "preferences.work_mode", "value": "hybrid", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "skill.hubspot.experience", "value": "7 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "language.french.proficiency", "value": "native", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "language.english.proficiency", "value": "fluent", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "compensation.minimum_base", "value": "75000", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
    ],
    "cv_v1": "CLAIRE DUPONT (Synthetic)\nEmail: claire.synthetic@test-candidate-b.eu | Paris, France\n\nPROFILE\nSenior Marketing Manager with 8+ years experience in B2B growth and multi-channel campaigns.\n\nEXPERIENCE\nHead of Digital Marketing | EuroGrowth SAS | 2019 - Present\n- Scaled inbound pipeline by 140% using HubSpot and SEO strategies.\n\nEDUCATION\nBA Communications (First Class Honours) | University of Edinburgh | 2015\n",
    "cv_v2": "CLAIRE DUPONT (Synthetic)\nEmail: claire.synthetic@test-candidate-b.eu | Paris, France\n\nPROFILE\nDirector of Marketing with 10+ years experience in omnichannel European expansion.\n\nEXPERIENCE\nDirector of Marketing | EuroGrowth SAS | 2019 - Present\n- Managed €2M marketing budget across France and Germany.\n",
    "interview_answers": {
        "preferences.work_mode": "hybrid",
        "compensation.minimum_base": "75000",
        "authorization.work_eligible": "True",
    },
    "jobs": {
        "strong_match": {
            "id": "job-b-strong",
            "title": "Senior Growth Marketing Manager",
            "company": "VentureScale EU",
            "location": "Paris (Hybrid)",
            "remote_ok": True,
            "min_salary": 80000,
            "required_skills": ["HubSpot", "Content Strategy", "SEO"],
            "required_credentials": [],
        },
        "weak_match": {
            "id": "job-b-weak",
            "title": "Junior Graphic Designer",
            "company": "Creative Studio",
            "location": "Paris (Hybrid)",
            "remote_ok": False,
            "min_salary": 35000,
            "required_skills": ["Photoshop", "Illustrator"],
            "required_credentials": [],
        },
        "gate_fail_location": {
            "id": "job-b-location-fail",
            "title": "Senior Marketing Manager (Tokyo On-Site)",
            "company": "AsiaPacific Retail",
            "location": "Tokyo, Japan",
            "remote_ok": False,
            "min_salary": 90000,
            "required_skills": ["HubSpot", "Brand Campaigns"],
            "required_credentials": [],
        },
        "ambiguous": {
            "id": "job-b-ambiguous",
            "title": "Product Marketing Specialist",
            "company": "SaaS Platform Inc",
            "location": "Paris (Hybrid)",
            "remote_ok": True,
            "min_salary": 70000,
            "required_skills": ["SEO", "Google Analytics"],
            "required_credentials": [],
        },
    },
    "expected_matches": {
        "ranking_order": ["job-b-strong", "job-b-ambiguous", "job-b-weak"],
        "gate_failures": {"job-b-location-fail": "location_mismatch"},
    },
}


CANDIDATE_C = {
    "profile": {
        "full_name": "Kenji Takahashi (Synthetic)",
        "email": "kenji.synthetic@test-candidate-c.jp",
        "phone": "+81-3-5555-0303",
        "location": "Nagoya, Japan",
        "work_mode": "onsite",
        "title": "Mechanical Engineer",
        "seniority": "early_career",
        "skills": ["SolidWorks", "AutoCAD", "GD&T", "Finite Element Analysis", "ASME standards"],
        "education": "BS Mechanical Engineering (84% marks)",
        "credentials": ["PE_LICENSE_EIT"],
        "min_salary": 450000,
        "currency": "JPY",
        "requires_sponsorship": False,
    },
    "facts": [
        {"key": "personal.name.full", "value": "Kenji Takahashi (Synthetic)", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.contact.email", "value": "kenji.synthetic@test-candidate-c.jp", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.location.city", "value": "Nagoya", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "credential.pe_license_eit", "value": "EIT Registered #88392", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "skill.solidworks.experience", "value": "3 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "language.japanese.proficiency", "value": "native", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "language.english.proficiency", "value": "professional", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "preferences.work_mode", "value": "onsite", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
    ],
    "cv_v1": "KENJI TAKAHASHI (Synthetic) / 高橋 健司\nEmail: kenji.synthetic@test-candidate-c.jp | Nagoya, Japan\n\nQUALIFICATIONS\nMechanical Design Engineer with EIT registration. 3 years CAD design in automotive manufacturing.\n\nCERTIFICATIONS\n- Professional Engineer Intern / EIT (License #88392)\n\nSKILLS\nSolidWorks, AutoCAD, GD&T, Finite Element Analysis (FEA), ASME Y14.5\n",
    "cv_v2": "KENJI TAKAHASHI (Synthetic) / 高橋 健司\nEmail: kenji.synthetic@test-candidate-c.jp | Nagoya, Japan\n\nQUALIFICATIONS\nMechanical Design Engineer (EIT #88392). 4 years automotive chassis engineering.\n\nSKILLS\nSolidWorks, AutoCAD, GD&T, FEA, ASME standards, CATIA\n",
    "interview_answers": {
        "preferences.work_mode": "onsite",
        "compensation.minimum_base": "450000",
        "credential.pe_license_eit": "EIT Registered #88392",
    },
    "jobs": {
        "strong_match": {
            "id": "job-c-strong",
            "title": "Mechanical Design Engineer",
            "company": "Precision Auto Tech",
            "location": "Nagoya (On-site)",
            "remote_ok": False,
            "min_salary": 480000,
            "required_skills": ["SolidWorks", "GD&T", "Finite Element Analysis"],
            "required_credentials": ["PE_LICENSE_EIT"],
        },
        "weak_match": {
            "id": "job-c-weak",
            "title": "Chemical Process Specialist",
            "company": "ChemIndustrial Co",
            "location": "Nagoya (On-site)",
            "remote_ok": False,
            "min_salary": 400000,
            "required_skills": ["Polymer Chemistry", "HPLC"],
            "required_credentials": [],
        },
        "gate_fail_credential": {
            "id": "job-c-cred-fail",
            "title": "Principal Lead PE Mechanical Engineer",
            "company": "Nuclear Energy Infrastructure",
            "location": "Nagoya (On-site)",
            "remote_ok": False,
            "min_salary": 800000,
            "required_skills": ["SolidWorks", "ASME standards"],
            "required_credentials": ["PE_FULL_STAMP"],  # Kenji only has EIT, NOT Full PE Stamp
        },
        "ambiguous": {
            "id": "job-c-ambiguous",
            "title": "CAD Drafter & Modeler",
            "company": "Manufacturing Partners",
            "location": "Nagoya (On-site)",
            "remote_ok": False,
            "min_salary": 420000,
            "required_skills": ["AutoCAD", "SolidWorks"],
            "required_credentials": [],
        },
    },
    "expected_matches": {
        "ranking_order": ["job-c-strong", "job-c-ambiguous", "job-c-weak"],
        "gate_failures": {"job-c-cred-fail": "credential_missing"},
    },
}


CANDIDATE_D = {
    "profile": {
        "full_name": "Maria Santos (Synthetic)",
        "email": "maria.synthetic@test-candidate-d.org",
        "phone": "+1-555-0404",
        "location": "Los Angeles, CA, USA",
        "work_mode": "onsite",
        "title": "Registered Nurse",
        "seniority": "mid",
        "skills": ["Patient Assessment", "Medication Administration", "Epic EHR", "IV Therapy", "Critical Care"],
        "education": "Associate Degree in Nursing (ADN), NCLEX-RN passed",
        "credentials": ["RN_STATE_LICENSE_CA", "BLS_CERT", "ACLS_CERT"],
        "min_salary": 45,  # $45/hour
        "currency": "USD",
        "requires_sponsorship": False,
    },
    "facts": [
        {"key": "personal.name.full", "value": "Maria Santos (Synthetic)", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.contact.email", "value": "maria.synthetic@test-candidate-d.org", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "personal.location.state", "value": "California", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "credential.rn_license", "value": "California Board of Registered Nursing #RN-849201", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "credential.bls_cert", "value": "AHA BLS Certified", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "skill.epic_ehr.experience", "value": "4 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "language.spanish.proficiency", "value": "working_professional", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
        {"key": "preferences.work_mode", "value": "onsite", "source": "USER_ENTERED", "confidence": "CONFIRMED"},
    ],
    "cv_v1": "MARIA SANTOS, RN (Synthetic)\nEmail: maria.synthetic@test-candidate-d.org | Los Angeles, CA\n\nLICENSURE & CERTIFICATIONS\n- Registered Nurse: California Board of Registered Nursing #RN-849201 (Active)\n- Basic Life Support (BLS) - American Heart Association\n- Advanced Cardiovascular Life Support (ACLS)\n\nCLINICAL EXPERIENCE\nStaff Nurse, Medical-Surgical / ICU Step-down | Metro Hospital | 2021 - Present\n- Administer medications and IV infusions; document care in Epic EHR.\n",
    "cv_v2": "MARIA SANTOS, RN (Synthetic)\nEmail: maria.synthetic@test-candidate-d.org | Los Angeles, CA\n\nLICENSURE & CERTIFICATIONS\n- Registered Nurse: California Board of Registered Nursing #RN-849201 (Active)\n- AHA BLS & ACLS Certified\n- Certified Medical-Surgical Registered Nurse (CMSRN)\n\nCLINICAL EXPERIENCE\nCharge Nurse | Metro Hospital | 2021 - Present\n",
    "interview_answers": {
        "preferences.work_mode": "onsite",
        "credential.rn_license": "California Board of Registered Nursing #RN-849201",
        "credential.bls_cert": "AHA BLS Certified",
    },
    "jobs": {
        "strong_match": {
            "id": "job-d-strong",
            "title": "Registered Nurse - ICU / Step-down",
            "company": "Pacific Coast Medical Center",
            "location": "Los Angeles, CA (On-site)",
            "remote_ok": False,
            "min_salary": 48,
            "required_skills": ["Patient Assessment", "Medication Administration", "Epic EHR"],
            "required_credentials": ["RN_STATE_LICENSE_CA"],
        },
        "weak_match": {
            "id": "job-d-weak",
            "title": "Hospital Receptionist & Scheduler",
            "company": "Clinic Network",
            "location": "Los Angeles, CA (On-site)",
            "remote_ok": False,
            "min_salary": 22,
            "required_skills": ["Customer Service", "Phone Scheduling"],
            "required_credentials": [],
        },
        "gate_fail_credential": {
            "id": "job-d-cred-fail",
            "title": "Licensed Nurse Practitioner (NP) - Urgent Care",
            "company": "Valley Health",
            "location": "Los Angeles, CA",
            "remote_ok": False,
            "min_salary": 75,
            "required_skills": ["Patient Assessment"],
            "required_credentials": ["NURSE_PRACTITIONER_LICENSE"],  # Requires NP license, Maria is RN
        },
        "ambiguous": {
            "id": "job-d-ambiguous",
            "title": "Occupational Health Nurse Coordinator",
            "company": "Aerospace Wellness Corp",
            "location": "El Segundo, CA",
            "remote_ok": False,
            "min_salary": 44,
            "required_skills": ["Epic EHR", "Patient Assessment"],
            "required_credentials": ["RN_STATE_LICENSE_CA"],
        },
    },
    "expected_matches": {
        "ranking_order": ["job-d-strong", "job-d-ambiguous", "job-d-weak"],
        "gate_failures": {"job-d-cred-fail": "credential_missing"},
    },
}


def make_candidate_fixtures() -> None:
    """Generate all candidate files for A, B, C, D."""
    candidates = {
        "a": CANDIDATE_A,
        "b": CANDIDATE_B,
        "c": CANDIDATE_C,
        "d": CANDIDATE_D,
    }

    for letter, data in candidates.items():
        cand_dir = FIXTURES_DIR / letter
        cand_dir.mkdir(parents=True, exist_ok=True)
        jobs_dir = cand_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)

        # 1. profile.yaml
        (cand_dir / "profile.yaml").write_text(
            yaml.safe_dump(data["profile"], sort_keys=False), encoding="utf-8"
        )

        # 2. facts.yaml
        (cand_dir / "facts.yaml").write_text(
            yaml.safe_dump(data["facts"], sort_keys=False), encoding="utf-8"
        )

        # 3. cv_v1.txt and cv_v2.txt
        (cand_dir / "cv_v1.txt").write_text(data["cv_v1"], encoding="utf-8")
        (cand_dir / "cv_v2.txt").write_text(data["cv_v2"], encoding="utf-8")

        # 4. interview_answers.yaml
        (cand_dir / "interview_answers.yaml").write_text(
            yaml.safe_dump(data["interview_answers"], sort_keys=False), encoding="utf-8"
        )

        # 5. jobs/*.json
        for job_name, job_dict in data["jobs"].items():
            (jobs_dir / f"{job_name}.json").write_text(
                json.dumps(job_dict, indent=2), encoding="utf-8"
            )

        # 6. expected_matches.yaml
        (cand_dir / "expected_matches.yaml").write_text(
            yaml.safe_dump(data["expected_matches"], sort_keys=False), encoding="utf-8"
        )

        print(f"Generated fixtures for Candidate {letter.upper()} at {cand_dir}")


if __name__ == "__main__":
    make_candidate_fixtures()
