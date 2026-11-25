"""Generate data/demo_samples.json: 40 Sympany-themed samples per demo channel.

Sympany is a Swiss health and property insurer based in Basel ("All the insurance you
need."): basic health insurance under KVG/LAMal (standard, family doctor, Telmed and HMO
models), supplementary insurance under VVG/LCA (hospital, dental, alternative medicine,
travel), accident, household contents & building, vehicle and business insurance, plus
the mySympany customer portal & app.

Distribution per channel (40): 16 benign, 10 reputational/abusive, 6 compliance,
3 market-abuse, 5 cyber. Every item references Sympany so the relevance filter passes;
the classifier then decides the actual risk category/severity.

All authors are fictional and every URL is a non-resolving demo placeholder (search page
plus a ``#sample-<n>`` fragment, or a ``tg://`` / ``wa://`` demo scheme). This script is
fully offline: it calls no external API.
"""

import json
from pathlib import Path

PRODUCTS = [
    "basic insurance", "Telmed model", "family doctor model", "HMO model",
    "hospital supplementary insurance", "dental insurance", "alternative medicine cover",
    "travel insurance", "accident insurance", "household contents insurance", "car insurance",
]

# (category, count) per channel
PLAN = [("benign", 16), ("reputational", 10), ("compliance", 6),
        ("market_abuse", 3), ("cyber", 5)]

T = {
    "x": {
        "benign": [
            "Just renewed my {p} with Sympany, smooth process 👍",
            "Sympany's {p} looks decent for a young family in Basel.",
            "Submitted a doctor's invoice in the mySympany app this morning, reimbursed within days. Great experience.",
            "Shoutout to the Sympany hotline for explaining the {p} clearly and patiently.",
            "Sympany just published its annual report, steady year for the Basel insurer.",
            "Comparing my {p} options for next year, Sympany is on the shortlist.",
            "Switched to the Sympany {p} this year. So far no complaints.",
            "Sympany sponsoring the local running event in Basel this weekend, nice to see.",
            "Merci vielmal Sympany, my {p} claim after the skiing trip was handled quickly.",
            "Reminder to self: check the Sympany {p} terms before the 30 November deadline.",
        ],
        "reputational": [
            "Sympany refused my {p} claim with zero explanation. Absolute scam. #BoycottSympany",
            "Worst service ever from @Sympany. Telling everyone to cancel their {p}.",
            "Sympany is a fraud, premiums up again and they still refuse every claim. Spread the word.",
            "Disgusting how Sympany treats loyal customers. Avoid this Krankenkasse.",
            "@Sympany your call centre is useless. 45 minutes on hold about my {p}. Disgrace.",
            "Sympany cheated my parents on their {p} reimbursement. Total rip-off.",
            "Never again Sympany. Hidden exclusions in the {p}, they just refused to pay.",
            "Sympany = liars. Promised fast reimbursement for my {p}, three months and nothing.",
        ],
        "compliance": [
            "A broker cold-called me 'on behalf of Sympany' and promised a CHF 200 cash bonus if I switch basic insurance. Is that even allowed?",
            "Sympany agent told me to omit my back problems on the health declaration for the hospital supplementary insurance so it gets accepted 😳",
            "Was told I can only get Sympany basic insurance if I also sign the hospital supplementary insurance. Pretty sure that's not legal.",
            "Sympany advisor promised my {p} premium is guaranteed to stay frozen for 5 years. Sounds fishy.",
            "Got a gift card offer from a 'Sympany partner' for switching my basic insurance. Smells like a commission scheme.",
        ],
        "market_abuse": [
            "Insider tip: Sympany's unpublished 2027 premium figures leaked, brokers are front-running the switching campaign before FOPH publishes 🚀",
            "Someone inside Sympany says the premium news drops next week. Coordinated push to move clients before it's public.",
            "Coordinated fake reviews campaign against Sympany on comparison portals tonight, everyone post at 8pm.",
        ],
        "cyber": [
            "Found Sympany customer data (AHV numbers + policy numbers) being sold on a Telegram channel.",
            "mySympany portal is leaking insured persons' details, screenshots going around.",
            "There's an exposed API key for the Sympany website in their JS bundle.",
            "Phishing SMS pretending to be Sympany asking for mySympany login and password. Don't click.",
            "Rumour that Sympany claims data with diagnoses got exposed in a misconfigured database.",
        ],
    },
    "telegram": {
        "benign": [
            "Anyone here using Sympany {p}? Thoughts on the service?",
            "Sympany info evening in Basel was useful, decent overview of the {p}.",
            "Comparing Sympany {p} vs other Swiss insurers, seems competitive this year.",
            "My Sympany advisor recommended the {p}, sounds reasonable for my situation.",
            "Good webinar by Sympany on how deductibles and the {p} work.",
            "FYI Sympany updated the {p} product sheet on their website.",
            "New to Switzerland, chose Sympany for my {p}. Registration was straightforward.",
            "The mySympany app now shows all invoices in one place, useful for expats.",
            "Sympany customer service answered in English, grateful for that as a newcomer.",
            "Sympany is based in Basel, been around a long time. Solid choice for {p} imo.",
        ],
        "reputational": [
            "Stay away from Sympany, they rejected my {p} claim for no reason. Scammers.",
            "Sympany is the worst, telling all my contacts to avoid them.",
            "Sympany refused to reimburse my {p} invoice, feels like fraud honestly.",
            "Boycott Sympany, they don't pay out claims. Pass it on.",
            "Sympany cheated my parents on their {p}. Disgraceful.",
            "Sympany customer service is useless, nobody answers emails about the {p}.",
            "Total rip-off: Sympany raised my premium and cut my {p} benefits.",
            "Sympany = liars. Their {p} brochure hides half the exclusions.",
        ],
        "compliance": [
            "A broker in this group is telling people to omit pre-existing conditions on Sympany dental and hospital insurance health declarations.",
            "Someone claiming to be Sympany staff is offering a cash bonus for switching basic insurance. DM him for the 'deal'.",
            "Broker here says Sympany basic insurance is only available together with dental insurance. Not true, right?",
            "Got a cold call from an 'independent broker' with my full details, pushing Sympany {p}. Where did they get my number?",
            "This guy offers to backdate Sympany {p} forms for a fee, screenshots below.",
        ],
        "market_abuse": [
            "Got word from a Sympany insider — unpublished premium figures for 2027, front-run the switching season now.",
            "Plan: coordinated fake reviews to push Sympany down on the comparison portals before 30 November.",
            "Leaked Sympany premium table before FOPH publication, DM for details, use it before it's public.",
        ],
        "cyber": [
            "Selling Sympany policyholder database, 50k records with AHV numbers. DM.",
            "Sympany admin panel credentials are floating around, anyone want access?",
            "Dumped Sympany customer emails + phone numbers + claims data, link in bio.",
            "mySympany login page clone is live, phishing kit with credentials capture for sale.",
            "Sympany internal VPN creds are on this paste, don't share outside.",
        ],
    },
    "whatsapp": {
        "benign": [
            "Reminder: Sympany {p} campaign materials are due Friday team.",
            "Customer wants info on Sympany {p}, sending the product sheet.",
            "Sympany team lunch at the Basel office 12:30, who's in?",
            "Updated Sympany {p} premium overview attached for the customer meeting.",
            "Sympany training on the new {p} is next Tuesday.",
            "Closed a Sympany {p} case today, good month so far.",
            "Customer happy with how fast Sympany handled the {p} claim, nice feedback.",
            "Don't forget: all Sympany posts go through the approval workflow before publishing.",
            "Sympany info stand at the Basel autumn fair this weekend, flyers for the {p} ready.",
            "Customer asked for the Sympany {p} terms in French, forwarding the PDF.",
        ],
        "reputational": [
            "Customer is furious, says Sympany is a scam after the {p} claim got refused.",
            "Another angry Sympany customer threatening to post about us online over their {p}.",
            "This Sympany complaint is going viral, the {p} refusal looks bad.",
            "Customer calling Sympany fraudsters in a Facebook group over a {p} dispute.",
            "PR issue: Sympany trending negatively over a {p} rejection.",
            "Customer says Sympany is the worst Krankenkasse and wants to boycott us, {p} invoice still unpaid.",
            "Local newspaper asking Sympany for a statement on the {p} complaints, customers call it a rip-off.",
            "Influencer with 80k followers calling Sympany liars over a refused {p} claim.",
        ],
        "compliance": [
            "Don't email this — keep it on WhatsApp. The Sympany broker side deal on commissions must not show up in the audit.",
            "Just tell the customer the Sympany {p} premium is guaranteed for 3 years, close it, deal with it later.",
            "We can backdate the Sympany {p} forms, compliance won't check.",
            "Use the purchased lead list and cold call them about Sympany {p}, nobody checks the industry agreement.",
            "Offer them a CHF 100 gift card if they move their basic insurance to Sympany, keep it off the record.",
            "Tell them basic insurance at Sympany is only possible with the hospital supplementary insurance, more commission for us.",
        ],
        "market_abuse": [
            "Heard from finance the Sympany 2027 premium figures — tell the brokers to move clients before it's published.",
            "Keep quiet but use the non-public Sympany premium data before next week's FOPH release.",
            "Non-public Sympany numbers attached, coordinate the switching campaign before disclosure.",
        ],
        "cyber": [
            "Found an exposed admin endpoint on the mySympany portal leaking AHV numbers + contact data, and a hardcoded API key.",
            "I have a copy of the Sympany customer database, we could sell the {p} leads.",
            "Sympany internal VPN creds are on this paste, don't share outside.",
            "Customer forwarded a phishing mail asking for her mySympany password, looks very real.",
            "Someone shared a Sympany claims data export with diagnoses in the wrong group chat.",
        ],
    },
    "quora": {
        "benign": [
            "What is the difference between Sympany's {p} and the standard model?",
            "Is the Sympany {p} worth it for a 30 year old in Basel? Looking for neutral views.",
            "How does Sympany {p} compare with other Swiss health insurers?",
            "Can someone explain how Sympany handles {p} reimbursements?",
            "Is Sympany a reputable insurer for {p}?",
            "What deductible makes sense with the Sympany {p}?",
            "How do I submit invoices for my {p} in the mySympany app?",
            "Does Sympany offer {p} for cross-border commuters?",
            "Sympany vs bigger insurers for {p} — is a smaller Basel insurer a good choice?",
            "How long does Sympany take to process a {p} claim? Mine was quick, curious about others.",
        ],
        "reputational": [
            "Is Sympany a scam? My {p} claim was refused and I feel cheated.",
            "Why does Sympany keep refusing {p} claims? Feels like fraud.",
            "Has anyone else been ripped off by Sympany on their {p}?",
            "Sympany refused my {p} reimbursement. How do I complain to the ombudsman?",
            "Why is everyone saying boycott Sympany over {p} claims?",
            "Is Sympany customer service really the worst? Weeks without an answer on my {p}.",
            "Should I avoid Sympany? Their {p} has hidden exclusions according to my neighbour.",
            "Are Sympany advisors liars or did I misunderstand my {p}?",
        ],
        "compliance": [
            "My Sympany advisor told me to hide my health condition on the alternative medicine cover health declaration. Is that allowed?",
            "A broker offered me a cash bonus to switch my basic insurance to Sympany. Should I report this?",
            "Is it legal for a broker to say Sympany basic insurance requires supplementary insurance?",
            "I keep getting cold calls about Sympany {p} even though I never gave my number. Isn't that banned?",
            "A Sympany broker said premiums for the {p} are guaranteed to stay frozen. Can they promise that?",
        ],
        "market_abuse": [
            "Someone claims to have leaked Sympany premium figures before FOPH publication — is using that legal?",
            "A group is coordinating fake reviews of Sympany on comparison portals. Is this manipulation?",
            "Is it insider abuse if a broker uses non-public Sympany premium data before it's published?",
        ],
        "cyber": [
            "I think Sympany's website leaked my AHV number and policy details — what do I do?",
            "Someone is selling a Sympany customer database online. Is my data safe?",
            "Found my mySympany account exposed due to a portal bug — how do I report a data leak?",
            "Got an SMS asking for my mySympany password. Is this phishing?",
            "Could my Sympany claims data with diagnoses have been exposed in a breach?",
        ],
    },
}

# Extra templates so the larger per-category counts don't repeat verbatim.
_EXTRA = {
    "x": {
        "benign": [
            "Sympany's {p} paperwork was surprisingly painless this year.",
            "Asked Sympany about the {p} via chat, answer within 10 minutes. Impressed.",
            "Good to see Sympany explain the {p} in plain language on their website.",
            "Neighbour recommended Sympany for {p}, will check it out.",
            "Sympany's {p} letter for next year arrived, all clear and on time.",
            "Neutral take: Sympany {p} is fine, nothing special, does the job.",
        ],
        "reputational": [
            "Sympany is the worst insurer in Basel, their {p} is useless when you actually need it.",
            "Cancelled my {p} with Sympany today. Scam company, avoid at all costs.",
            "Boycott Sympany until they pay my {p} invoice. RT if they cheated you too.",
            "Sympany customer service hung up on me twice about my {p}. Disgrace.",
        ],
        "compliance": [
            "Broker at the train station handing out 'Sympany switching bonus' vouchers for basic insurance. Is that legit?",
            "Sympany rep said the hospital supplementary insurance needs no health questions at all. That can't be right.",
        ],
        "market_abuse": [
            "Leaked Sympany internal premium forecast circulating among brokers before the official release.",
            "Brokers coordinating to dump Sympany clients using non-public premium numbers before FOPH day.",
        ],
        "cyber": [
            "Sympany customer list with AHV numbers posted on a hacking forum, apparently from an old export.",
            "Fake mySympany app in a third-party store asking for login credentials. Report it.",
        ],
    },
    "telegram": {
        "benign": [
            "Sympany {p} renewal done online in 5 minutes, happy with it.",
            "Question for the group: is the Sympany {p} good value? Heard positive things.",
            "Sympany's {p} brochure finally available in English, useful for expats.",
            "Neutral review: Sympany {p} works as expected, no surprises.",
            "Sympany helped me understand the {p} deductible options, thanks to the advisor.",
            "Sympany hotline was reachable on Saturday, nice for the {p} questions.",
        ],
        "reputational": [
            "Sympany is a scam, my {p} claim has been 'in review' for 4 months.",
            "Avoid Sympany. Worst {p} experience of my life.",
            "Sympany customer advisors are liars, my {p} is not what they sold me.",
            "Sympany refused my {p} reimbursement again. Boycott them.",
        ],
        "compliance": [
            "Broker in this channel guarantees Sympany {p} premiums won't increase. That's a lie, right?",
            "Someone is selling 'pre-approved' Sympany hospital insurance applications without health declaration. Huge red flag.",
        ],
        "market_abuse": [
            "Insider from Sympany sharing next year's premium table here before FOPH, use it before it's public.",
            "Coordinated fake reviews of Sympany planned for tonight, post 1-star everywhere.",
        ],
        "cyber": [
            "Sympany customer data leak: AHV numbers and addresses posted in a dark web dump.",
        ],
    },
    "whatsapp": {
        "benign": [
            "Sympany {p} quote sent to the customer, waiting for feedback.",
            "Nice thank-you card from a Sympany {p} customer today.",
            "Sympany {p} FAQ updated on the intranet, please read before customer calls.",
            "Sympany customer satisfaction results are in, good feedback on the {p} team.",
            "Sympany office closed Monday for the holiday, {p} queries on Tuesday.",
            "Sympany {p} webinar recording is on the shared drive.",
        ],
        "reputational": [
            "Customer posted a 1-star review: 'Sympany is a scam, avoid' after the {p} refusal.",
            "Customer threatening to go to the media saying Sympany cheated him on the {p}.",
            "Sympany getting hammered on social for the {p} delays, people calling us useless.",
            "Customer started a boycott Sympany thread in a parents' group over a {p} claim.",
        ],
        "compliance": [
            "Skip the health declaration for the Sympany dental insurance, I'll fill it in for the customer later.",
        ],
        "market_abuse": [
            "Insider numbers on Sympany premiums attached, share with the brokers before FOPH publishes.",
            "Coordinate with the partner brokers: front-run the switching wave with the non-public Sympany data.",
        ],
        "cyber": [
            "Sympany customer export with AHV numbers saved on a public cloud link by mistake.",
        ],
    },
    "quora": {
        "benign": [
            "What does the Sympany {p} cover exactly?",
            "Is Sympany a good choice for {p} if I live in Basel-Stadt?",
            "How do I switch my {p} to Sympany before the deadline?",
            "Has anyone had a positive experience with Sympany {p} claims?",
            "What are the pros and cons of the Sympany {p}?",
            "How does the Sympany {p} work for families with children?",
        ],
        "reputational": [
            "Why is Sympany so bad at handling {p} claims? Is it a scam?",
            "Did Sympany cheat anyone else on their {p}?",
            "Is Sympany the worst insurer in Switzerland for {p}?",
            "Should I boycott Sympany after they refused my {p} claim?",
        ],
        "compliance": [
            "Is it allowed for a broker to give me a gift card for switching basic insurance to Sympany?",
            "A broker filled in my Sympany hospital supplementary insurance health declaration for me and left things out. What now?",
        ],
        "market_abuse": [
            "Is it legal for brokers to use leaked Sympany premium tables before they are published?",
            "Someone is organising coordinated fake reviews against Sympany. How do I report that?",
        ],
        "cyber": [
            "Is the Sympany data leak with AHV numbers real? How do I check if I'm affected?",
        ],
    },
}
for _ch, _cats in _EXTRA.items():
    for _cat, _items in _cats.items():
        T[_ch][_cat].extend(_items)

URL = {
    "x": "https://x.com/search?q=Sympany#sample-{n}",
    "telegram": "tg://demo/sympany/sample-{n}",
    "whatsapp": "wa://demo/sympany/sample-{n}",
    "quora": "https://www.quora.com/search?q=Sympany#sample-{n}",
}
AUTHORS = {
    "x": ["lena_k_bs", "zueri_spartipps", "marco_r_ti", "basel_familie", "praemien_watch", "chriggel_88"],
    "telegram": ["finanz_forum_ch", "expat_zurich_42", "budget_basel", "anon_ch_trader", "rhyy_member"],
    "whatsapp": ["wa_member_{n:03d}", "team_lead_basel", "broker_desk_ch", "agency_west", "ops_support"],
    "quora": ["quora_user_{n}", "Marco R.", "Lena K.", "Sophie M.", "neutral_reviewer", "new_in_basel"],
}


def build(channel: str) -> list[dict]:
    out, n = [], 0
    cats = T[channel]
    for cat, count in PLAN:
        templates = cats[cat]
        for i in range(count):
            tpl = templates[i % len(templates)]
            product = PRODUCTS[(n + i // len(templates)) % len(PRODUCTS)]
            text = tpl.replace("{p}", product)
            authors = AUTHORS[channel]
            author = authors[n % len(authors)].format(n=n + 1)
            out.append({
                "id": f"{channel}-{n+1}",
                "author_id": author,
                "text": text,
                "url": URL[channel].format(n=n + 1),
            })
            n += 1
    return out


def main() -> None:
    samples = {ch: build(ch) for ch in T}
    path = Path(__file__).resolve().parent.parent / "data" / "demo_samples.json"
    path.write_text(json.dumps(samples, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    for ch, items in samples.items():
        print(f"  {ch}: {len(items)} samples")


if __name__ == "__main__":
    main()
