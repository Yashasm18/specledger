# UniHack 2026 — Participation Guide

Source: [UniHack on Hack2Skill](https://hack2skill.com/event/unilog2026/)

## What this hackathon is

UniHack is an AI innovation hackathon by Unilog. The goal is to build a working prototype or proof of concept for:

> AI-powered product intelligence for industrial commerce.

Industrial businesses have product information spread across websites, catalogues, and technical documents. Your solution should turn incomplete or messy information into reliable, structured, commerce-ready product data.

## Who can participate

- Engineering students enrolled at a recognized college or university in India.
- You may participate alone or in a team of up to 4 people.
- Participation is free.

## Important dates

| Phase | Date |
|---|---|
| Registration | 29 July – 23 August 2026 |
| Prototype submission | 29 July – 23 August 2026 |
| Evaluation | 24 August – 1 September 2026 |
| Finale / winner announcement | 4 September 2026 |

Registration and submission currently share the same deadline, so do not wait until the final day.

## What you need to build

Build an MVP/POC that can do some or all of the following:

1. Accept limited product information, such as a short description, catalogue row, webpage, PDF, or technical document.
2. Extract and normalize useful product attributes.
3. Generate structured product data suitable for a commerce catalogue.
4. Identify missing, contradictory, or low-confidence information.
5. Enrich the product record using AI, while clearly showing the source or reasoning.
6. Scale to many products rather than handling only one hard-coded example.

Expected outcomes listed by the event are structured data generation, improved accuracy and consistency, AI validation/enrichment, and a scalable catalogue engine.

## A strong beginner-friendly project idea

### Product Intelligence Copilot

Create a web app where a user uploads a product PDF, URL, or text description. The app:

- extracts product name, category, specifications, dimensions, materials, certifications, and compatible products;
- outputs a validated JSON product record;
- flags missing or conflicting attributes;
- labels every generated value as `source found`, `AI inferred`, or `needs review`;
- exports the final record as JSON or CSV.

This directly matches the challenge and is achievable as a focused prototype.

## Suggested technical stack

The event recommends or permits AI/ML, Generative AI, LLMs, Python, NLP, data processing, cloud technologies, APIs, automation frameworks, web technologies, prompt engineering, machine-learning frameworks, Java, and open-source technologies.

A practical stack:

- Frontend: React or a simple Streamlit interface
- Backend: Python + FastAPI
- Extraction: PyMuPDF for PDFs, BeautifulSoup for webpages
- AI: an LLM API with structured JSON output
- Validation: Pydantic + custom business rules
- Search/retrieval: embeddings plus a vector store if needed
- Storage: SQLite for the demo, PostgreSQL or cloud storage for scale
- Deployment: any reliable cloud host

## What to submit

The portal says registered participants submit their prototype through the hackathon portal before the deadline. Prepare these items even if the exact form fields are only visible after login:

- working deployed demo;
- source-code repository;
- 2–3 minute demo video;
- short problem/solution explanation;
- architecture diagram;
- sample input and output;
- setup instructions;
- technology and API list;
- limitations, risks, and future improvements;
- team member details.

## How judging works

The published evaluation factors are:

- innovation;
- technical implementation;
- business relevance;
- scalability;
- overall impact.

To score well, demonstrate a complete flow with real-looking industrial product data, measurable extraction accuracy, explainability, validation, and a polished user experience. A small reliable prototype is better than a large unfinished platform.

## Prize and opportunities

Total prize pool: **₹5,00,000**

- Winner: ₹2,00,000
- 1st runner-up: ₹1,50,000
- 2nd runner-up: ₹1,00,000
- Two special awards: ₹25,000 each

Top performers may be considered for internships, PPOs, or full-time roles at Unilog.

Important IP note: the event page says ownership of the IP rights for winning solutions will be transferred to the program organizers after the award is confirmed. Read the official terms carefully before submitting anything proprietary.

## What to do now

1. Register on Hack2Skill and open the participant dashboard.
2. Decide whether to work solo or invite up to 3 teammates.
3. Choose one narrow product-data workflow for the MVP.
4. Collect 5–10 sample industrial products for testing.
5. Build extraction → normalization → validation → export.
6. Add source citations and confidence labels to every AI-generated field.
7. Deploy the demo and prepare the submission materials.
8. Submit before 23 August 2026 and retain screenshots/confirmation.

## Access limitation

The public event data is available without login. The roadmap, team dashboard, submissions, forms, resources, and other participant-specific pages require a Hack2Skill login/token. I did not attempt to bypass that authentication. Once you log in, share screenshots or copied text from any participant-only page and I can explain each field and help complete the submission.

Support email listed on the event: support@hack2skill.com

