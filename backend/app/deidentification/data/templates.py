"""Synthetic clinical-transcript templates, 4 families.

Slots: {name} full name, {first} first name only, {date}, {phone}, {mrn},
{loc}, {age}. A numeric suffix ({name2}) requests a distinct fill of the
same type. Titles (dr./mr./ms.) sit OUTSIDE the slot on purpose: teacher
annotators disagree about including them, which is exactly the boundary
uncertainty the soft labels should carry.

HARD_NEGATIVE templates contain no PHI but are dense with things a naive
model confuses for it: lab values, doses, eponymous disease names,
relative dates, scale scores.
"""

DIALOGUE = [
    "doctor: good morning {name}, how have you been feeling since {date}?\npatient: honestly, the cough has gotten a little worse at night.",
    "nurse: before we start, can you confirm your date of birth?\npatient: it's {date}.\nnurse: and the best number to reach you?\npatient: {phone}.",
    "doctor: so {first}, the chart says you're {age} years old and still living in {loc}, is that right?\npatient: yes, that's correct.",
    "receptionist: i have your medical record number as {mrn}, and a callback at {phone}. anything change?\npatient: no, that's all the same.",
    "doctor: your referral came from dr. {name} over in {loc} on {date}.\npatient: right, she said you'd have the imaging by now.",
    "patient: my daughter {first} usually drives me to appointments.\ndoctor: good — please have her call {phone} to set up the follow-up.",
    "doctor: thanks for coming in, {name}. when did the headaches start?\npatient: around {date}, maybe a few days earlier.",
    "nurse: mr. {name}, we'll get you roomed in a moment.\npatient: thank you kindly.",
    "doctor: any family history i should know about?\npatient: my father passed at {age} from a heart attack, back when we lived in {loc}.",
    "pharmacist: the refill under record {mrn} is ready after 2 pm.\npatient: great, i'll come by after work.",
    "doctor: ms. {name}, your labs from {date} look much better.\npatient: that's a relief, honestly.",
    "patient: can you send the results to my new address in {loc}?\nnurse: of course — and is {phone} still the right number?",
    "doctor: {first}, i want to see you again on {date}. sooner if the swelling returns.\npatient: understood.",
    "nurse: how old is your son now?\npatient: he just turned {age} in the spring.",
]

INTAKE = [
    "patient name: {name}\ndate of birth: {date}\nmrn: {mrn}\ncontact: {phone}\ncity: {loc}",
    "referral received {date} for {name} (mrn {mrn}) from the {loc} family practice.",
    "emergency contact: {name}, reachable at {phone}.",
    "appointment confirmation — {name}, {date} at 9:30 am, cardiology, {loc} campus.",
    "insurance verification completed on {date} for member {name}, age {age}.",
    "chart audit: record {mrn} last updated {date}; verified phone {phone}.",
    "transfer summary: patient {name}, {age} years old, transferred from {loc} general hospital on {date}.",
    "pharmacy callback log — {date}: left message at {phone} regarding prior authorization.",
    "lab requisition for {name}, mrn {mrn}, collected {date}, fasting panel.",
    "consent form signed by {name} on {date}; witness: {name2}.",
    "discharge checklist for mrn {mrn}: follow-up scheduled {date}, ride home confirmed with {first} at {phone}.",
    "demographics update: {name}, now residing in {loc}, home number {phone}.",
]

NARRATIVE = [
    "{name} is a {age}-year-old patient from {loc} who presented on {date} with chest pain radiating to the left arm.",
    "the patient was seen in clinic by dr. {name} on {date}; a follow-up call to {phone} is planned within one week.",
    "mr. {name}, mrn {mrn}, returns for routine diabetes management. he remains active and lives independently in {loc}.",
    "this {age}-year-old was last hospitalized on {date} at the {loc} medical center for community-acquired pneumonia.",
    "records under mrn {mrn} were reconciled with the outside chart received {date}.",
    "per the patient's spouse, {name}, symptoms began roughly two days before the {date} visit.",
    "the patient, {name}, aged {age}, denies fever, chills, or recent travel outside {loc}.",
    "attempts to reach the patient at {phone} on {date} were unsuccessful; a letter was mailed instead.",
    "dr. {name2} assumed care from dr. {name} following the {date} transfer.",
    "ms. {name} is a {age}-year-old presenting for preoperative clearance ahead of her {date} procedure.",
    "case discussed at tumor board on {date}; the patient ({mrn}) will be contacted at {phone} with the consensus plan.",
    "the home health agency in {loc} visited on {date} and reports good wound healing.",
]

HARD_NEGATIVE = [
    "blood pressure was 132 over 84 with a heart rate of 78 and oxygen saturation of 97 percent on room air.",
    "started metformin 500 mg twice daily with meals; counseled on gi side effects.",
    "babinski sign negative bilaterally; romberg test unremarkable.",
    "a1c came back at 7.2 percent, down from 8.1 percent three months ago.",
    "the glasgow coma scale score was 15 on arrival and remained stable overnight.",
    "chest x-ray showed no acute cardiopulmonary process; ekg demonstrated normal sinus rhythm at 72 beats per minute.",
    "potassium 4.1, sodium 138, creatinine 0.9, egfr greater than 60.",
    "continue lisinopril 10 mg daily and recheck a basic metabolic panel in two weeks.",
    "parkinson disease symptoms remain stable on the current carbidopa-levodopa regimen.",
    "reviewed hodgkin lymphoma staging with the multidisciplinary team; pet scheduled for next month.",
    "administered 2 liters of oxygen via nasal cannula with good response within minutes.",
    "colonoscopy prep instructions reviewed; clear liquids after midnight the day before the procedure.",
    "wound measures 2.3 by 1.1 centimeters with granulation tissue and no purulent drainage.",
    "the patient tolerated the procedure well and was discharged to the recovery area in stable condition.",
]

TEMPLATES: list[tuple[str, str]] = (
    [("dialogue", t) for t in DIALOGUE]
    + [("intake", t) for t in INTAKE]
    + [("narrative", t) for t in NARRATIVE]
    + [("hard_negative", t) for t in HARD_NEGATIVE]
)

PHI_FAMILIES = ("dialogue", "intake", "narrative")
