# Signal email template — Workflow D (v1, AWAITING HARP APPROVAL)
#
# This is an LLM generation prompt, not a slot-fill template. Same contract as
# referral_email.md: fixed blocks are reproduced verbatim, generated blocks are
# written from research and mechanically checked afterwards.
#
# WHAT MAKES THIS DIFFERENT FROM THE REFERRAL TEMPLATE, AND WHY IT EXISTS:
# the referral template's Block 1 and Block 7 assert an introduction from
# Manpreet Singh. For a scanned lead that referral does not exist. Reusing it
# would fabricate the single most checkable claim in the email. This template
# never mentions Manpreet, Singh Capital, or any referral, and email_drafter's
# check list for Workflow D treats any such mention as a hard failure, not a
# style note.
#
# The cold-open substitute for the referral is the POSTING. It is public, it is
# recent, and it is the reason we are writing. It carries the same "this is not
# spam" weight a referral does, provided it is stated exactly right.
#
# Slots resolved before the LLM call:
#   {{poc_first_name}}   - Apollo, or the scanner POC hint
#   {{poc_email}}        - Apollo
#   {{firm_short}}       - LLM-derived common name, no legal suffix
#   {{posting_title}}    - VERBATIM from the scanned posting. Never reworded.
#   {{posting_url}}      - the posting URL, verbatim
#   {{posting_count}}    - distinct titles this firm has open right now
#   {{posting_titles}}   - all distinct titles, when count > 1
#   {{research_object}}  - the gate's research dict: firm_oneliner,
#                          disclosed_figure, disclosed_label, asset_class,
#                          geography, capital_stack, founded_year, hook_1,
#                          hook_2, service_fit

## Subject (generated from one fixed pattern, never free-written)

Single posting:      Your {{posting_title}} opening
Multiple postings:   Your {{posting_count}} open finance roles

The posting title in the subject is copied verbatim. No adjectives, no
"regarding", no question marks.

## To
{{poc_email}}

## Email structure

### BLOCK 1 - Greeting + the signal (SLOT-FILLED, not LLM-written)

Hi {{poc_first_name}},

You have a {{posting_title}} open at {{firm_short}}. I run X Analyst. We are the alternative to that hire.

When {{posting_count}} > 1, sentence one becomes:
You have {{posting_count}} finance roles open at {{firm_short}} right now, including {{posting_title}}.

This block is assembled in Python, not generated. The posting title and the
firm name are the two facts that must never be wrong, and the way to guarantee
that is to never let a model retype them.

### BLOCK 2 - Firm-specific context (LLM-GENERATED, 1-2 sentences, 15-30 words)

One or two sentences proving we know their actual business, so the email does
not read as a bot that scraped a job board. Draw on {{research_object}}: asset
class, geography, capital stack, portfolio scale, founding year.

Rules:
- Must be specific to THIS firm. No industry commentary.
- Every number copied verbatim from {{research_object}}. Never re-derive,
  never round. Same figure discipline as the referral template: state
  disclosed_figure with disclosed_label, never the internal haircut number.
- If aum_tag is AUM_ESTIMATED with proxy_type "units", there is no dollar
  figure for this firm. State the quantity itself. Invent no dollar amount.
- If aum_tag is AUM_ESTIMATED with an invested-capital proxy, frame it with
  "since {{founded_year}}". It is cumulative, not a current asset base.
- No compliments. No "I noticed". No "I came across". Facts only.
- If research is thin, use firm_oneliner as one sentence and set
  thin_personalization.

Good example:
"You run about 4,000 multifamily units across Ohio and Kentucky, most of it
JV equity with institutional LPs."

Bad example:
"I came across your impressive portfolio and was excited to learn more about
your growth in the multifamily space."

### BLOCK 3 - The math (FIXED, verbatim)

A US fully loaded hire for that seat runs $145K to $180K. We place a dedicated senior operator on your team for $55K to $75K, exclusively yours, embedded in your systems and your close calendar, live in 10 days.

This is the deck's own pre-approved language. Both ranges are disclosed
figures and are whitelisted in the deck money-scrub. They are never
recalculated per firm, never turned into a percentage, and never presented as
a saving specific to this firm's actual salary band, which we do not know.

### BLOCK 4 - Why this seat specifically (LLM-GENERATED, 2-3 sentences, 30-50 words)

Map the role they are hiring for to what our operators actually do, then name
the concrete cost of the alternative. Use {{research_object.service_fit}}.

X Analyst sells embedded senior offshore finance professionals: property-level
books and month-end close, bank reconciliations, AP/AR and tenant billing, CAM
reconciliations and true-ups, budget vs actual variance reporting, lender and
covenant packages, owner distributions and monthly owner reports, across Yardi,
RealPage, and Entrata. State the offering from this list only. Do not invent an
offering, do not describe X Analyst as software, a platform, or PropTech.

Rules:
- Connect to the SPECIFIC posting title. A CAM analyst opening and a fund
  controller opening are not the same pitch.
- Name a concrete cost, not an abstract risk. Whose night it costs, what
  breaks first, how long the seat stays empty. "Risks disrupting reporting"
  is consultant-speak and fails review.
- Do not repeat a number Block 2 already used.
- The role-to-function mapping must lead. The length guard trims trailing
  sentences first, so anything essential goes first.

Good example:
"A property accountant search takes three months and the close does not
pause while you run it. Our operators are already doing CAM true-ups and
lender packages in Yardi on day 10, and they stay yours."

Bad example:
"We offer comprehensive solutions that can help streamline your accounting
operations and unlock efficiency across your portfolio."

### BLOCK 5 - CTA (FIXED, verbatim)

Can we do a call next week? I'd bring our Head of Delivery, ex-Blackstone and Goldman Sachs, one of the first people to transition large funds' operations to India. Thirty minutes with him is useful even if we never work together.

### BLOCK 6 - Signature + P.S. (FIXED, verbatim)

Harp
Founder, X Analyst

P.S. The deck is attached. The posting is here if I have the wrong one: {{posting_url}}

The P.S. carries the posting URL. It is the honest version of a signal email:
we say where we got the signal, and we give them the way to correct us.

---

## Generation rules (system-level, never shown in the email)

1. LENGTH GUARD: body max 260 words (EMAIL_MAX_WORDS). Fixed blocks assemble
   to roughly 130 words, so the generated blocks have real room. Trim Block 4
   first, then Block 2, whole trailing sentences only, never mid-sentence.

2. REQUIRED FACTS (mechanically checked, drafting fails without them):
   - {{posting_title}} appears in Block 1, character-for-character.
   - {{firm_short}} appears in Block 1.
   - {{posting_url}} appears in Block 6.
   - Both dollar ranges appear in Block 3 unmodified.
   The posting title, firm name, and URL join the grounding corpus, which is
   what makes these mechanically verifiable rather than a prompt request.

3. FORBIDDEN CLAIMS (any hit is a hard failure, not a retry):
   - Any mention of Manpreet, Singh Capital, a referral, an introduction, a
     mutual connection, or "we were connected".
   - Any claim we have spoken to this firm before, or that anyone suggested
     the outreach.
   - Any invented figure about the firm, including a computed saving.
   - Any claim about their current provider, their systems, or their team
     size that {{research_object}} does not support. We know they are hiring.
     We do not know who does the work today.

4. ANTI-AI WRITING RULES: identical to referral_email.md section 3. No em
   dashes anywhere in this template's generated OR fixed blocks (unlike the
   referral template, which keeps them in Harp's original fixed prose, this
   template is new text so it starts clean). No semicolons in generated
   blocks. Straight quotes only. Same banned phrase and banned word lists.

5. TONE: Harp's voice. A cold email that earns the reply by being useful in
   the first line. Direct, no hedging, no throat-clearing, no "I hope this
   finds you well".

6. FALLBACK (thin_personalization): Block 2 becomes firm_oneliner as one
   sentence. Block 4 reverts to this fixed paragraph:
   "The search takes three months and the close does not pause while you run
   it. Most firms bridge it by paying a provider whose partners never open
   their ledger, or by pushing it onto a controller who is already at
   capacity. Both cost more than the seat."

7. FINAL SELF-CHECK: (a) Would this email make sense if the posting did not
   exist? If yes, the signal is not doing any work and Block 1 or Block 4 is
   wrong. (b) Could you swap in any firm name and it still reads? If yes,
   Block 2 is filler. (c) Is there anything in here we could not point to a
   source for? If yes, delete it.
