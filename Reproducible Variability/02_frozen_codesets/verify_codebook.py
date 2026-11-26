# === Code set integrity check ===
# Run from this directory:  python3 verify_codebook.py
# Confirms all 20 frozen code sets match the exact code count and SHA-256
# checksum that every port implementation asserts at load time, so the lists
# published here are provably the ones the reported cohorts were built from.
# Checks every frozen codebook file: exact code count AND content checksum
# (catches drops, adds, and silent single-code substitutions).
import json, glob, os, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))

EXPECT = {
    'chronic_lower_respiratory_disease_clrd__diagnosis_code__verityfoundation.json': (48, '46ab61bc072b5e9a'),
    'conditions_that_frequently_require_chronic_systematic_corticosteroids__diagnosis_code__verityfoundation.json': (1219, '4124a5d0a418bf64'),
    'cystic_fibrosis__diagnosis_code__verityfoundation.json': (6, 'dc7421ecb6bd58ec'),
    'dpp_4i__ndc__verityfoundation.json': (437, 'd7773387a9d5a6e6'),
    'drugs_for_clrd__ndc__verityfoundation.json': (12025, '9d157567109e0859'),
    'drugs_for_diabetes__ndc__verityfoundation.json': (8170, 'f67b4b0aa4b59bec'),
    'glp_1ra__ndc__verityfoundation.json': (172, 'a31e5fa4c7d3ba25'),
    'glp_1ra_without_insulin__ndc__verityfoundation.json': (163, 'e2b0ae8663f4f02a'),
    'insulin_drugs_and_devices__ndc__verityfoundation.json': (1142, '04f8a0f0e2f9397c'),
    'lower_respiratory_tract_infection_respiratory_distress_or_respiratory_failure__diagnosis_code__verityfoundation.json': (99, '6c29c022d315e7de'),
    'lung_cancer__diagnosis_code__verityfoundation.json': (35, 'faa66a492c7fad54'),
    'metformin__ndc__verityfoundation.json': (3930, 'fabaaee5fa2cb139'),
    'pregnancy_conditions_procedures_and_observations__diagnosis_code__verityfoundation.json': (3434, '90a5ef8949e39494'),
    'pregnancy_conditions_procedures_and_observations__procedure_code__verityfoundation.json': (42, 'b2fe8c1bbd144be5'),
    'pulmonary_embolism__diagnosis_code__verityfoundation.json': (13, 'c09283295125bc0c'),
    'pulmonary_hypertension__diagnosis_code__verityfoundation.json': (12, 'b6e5e8f0e2d099c5'),
    'systematic_corticosteroids__ndc__verityfoundation.json': (7625, '18781ec58e92f5e2'),
    'thyroid_carcinoma__diagnosis_code__verityfoundation.json': (1, '27157acafbaa3714'),
    'type_1_diabetes_mellitus__diagnosis_code__verityfoundation.json': (124, 'a9e2f7016a884a9a'),
    'type_2_diabetes_mellitus__diagnosis_code__verityfoundation.json': (238, '9a2392ddbdb32de6'),
}

def h(cs): return hashlib.sha256(','.join(cs).encode()).hexdigest()[:16]
present=bad=0
for fn,(n,hh) in sorted(EXPECT.items()):
    p=os.path.join(HERE, fn)
    if not os.path.exists(p): print('MISSING', fn); continue
    cl=json.load(open(p)).get('codes_list',[]); present+=1
    if len(cl)!=n: print('COUNT  ', fn, 'expected',n,'got',len(cl)); bad+=1
    elif h(cl)!=hh: print('CONTENT', fn, 'checksum mismatch — a code differs from canonical'); bad+=1
extra=[os.path.basename(p) for p in glob.glob(os.path.join(HERE,'*.json')) if os.path.basename(p) not in EXPECT]
for f in extra: print('EXTRA:', f)
print('present:',present,'/',len(EXPECT),'  problems:',bad)
print('RESULT:', 'OK' if present==len(EXPECT) and bad==0 else 'CHECK FAILED')
