Grey MVP — Final Product Blueprint
1. Product Definition
Grey is an AI companion for final-year students that helps them discover a real-world FYP idea, validate it with credible evidence, design a feasible implementation plan, and generate a supervisor-ready proposal.
The MVP focuses on one complete outcome:
A student comes with no clear FYP idea and leaves with a validated, evidence-backed, technically feasible, supervisor-ready FYP proposal.
Grey is not intended to behave like an open-ended chatbot. The experience should feel natural and conversational, but the journey underneath should be structured and controlled.

2. Core Grey MVP Promise
Grey helps final-year students discover a real-world FYP idea, validate it with evidence, design a feasible implementation plan, and generate a supervisor-ready proposal.
Grey should reduce the four biggest uncertainties students face at the beginning of an FYP:
What should I build?
Is this a real problem?
Can I actually build it?
Can I confidently present it to my supervisor?

3. Core Product Philosophy
Grey follows one fundamental rule:
Grey does not invent FYP ideas first and look for justification later. Grey discovers real-world problems first and derives feasible student projects from them.
The MVP flow is:
Industry
→ Branch
→ Evidence Research
→ Real Problems
→ Problem Selection
→ Automatic Functional-Area Classification
→ FYP Design
→ Dataset / AI / Technology Plan
→ Feasibility
→ Supervisor Readiness
→ Proposal

4. Structured Experience, Not an Open Chatbot
Grey should not give the student unlimited freedom to continuously brainstorm, restart, or ask for endless unrelated ideas.
The interaction should be:
Natural conversation on the surface, structured workflow underneath.
Grey always knows the current stage and guides the student toward the next required decision.
The student can still speak naturally, but Grey controls the journey.

5. Step 1 — Student Starts the FYP Journey
The student may say:
“I need an FYP.”
“Help me find an FYP idea.”
“I need an AI project.”
Grey recognizes that the student wants to start FYP discovery.
Grey begins the structured workflow.

6. Step 2 — Industry Selection
Grey asks:
Which industry do you want to build your FYP for?
The interface should preferably show selectable industry options.
Examples:
Healthcare
Defense
Finance
Agriculture
Education
Cybersecurity
Transportation
Manufacturing
Energy
Logistics
Retail
Smart Cities
Environment
Telecommunications
Government Services
The student selects one.
Example:
Defense
Grey stores this selection in the Project Brain.

7. Step 3 — Branch Selection
Grey now shows branches relevant to the selected industry.
Example:
Defense
Army
Navy
Air Force
Cyber Defense
Defense Logistics
Intelligence
Disaster / Emergency Operations
The student selects:
Navy
Grey stores:
Industry: Defense
Branch: Navy

8. Functional Area Is NOT Asked From the Student
Grey should not ask the student to select a functional area at this stage.
A technology student may understand:
Industry = Defense
and:
Branch = Navy
but may not know terms such as:
Maritime Surveillance
Fleet Operations
Maritime Situational Awareness
Predictive Maintenance
Vessel Traffic Management
Grey should understand these concepts for the student.
Therefore the student only needs to select the industry and branch.
Grey discovers the relevant problem areas automatically.

9. Step 4 — Evidence Research
Once the branch is selected, Grey performs targeted real-world research.
Grey investigates:
Startups
Established companies
Government initiatives
Government reports
Official programs
Recent industry news
Research papers
University research
Public challenges
Open-source projects
Public datasets
Industry reports
The central research question is:
What real problems are organizations currently trying to solve in this branch?
Example:
Defense → Navy
Grey investigates real problems currently being addressed in naval and maritime technology.

10. Evidence Transparency
Grey must clearly show where its information comes from.
Every important source should include:
Source title
Organization/company
Source type
Date
Problem being addressed
Relevant insight
Source link
Why this source matters
The student should always be able to understand:
“This is where Grey got this idea.”
Transparency is one of Grey’s core differentiators.

11. Evidence Quality
Grey should prioritize high-quality evidence.
Tier A — Primary Evidence
Official startup website
Official company website
Government publication
Government initiative
Peer-reviewed research
Official dataset
Official technical documentation
Tier B — Strong Secondary Evidence
Reputable news organization
Established technology publication
Recognized industry publication
University research announcement
Tier C — Discovery Evidence
Startup directories
Accelerator profiles
Industry blogs
Aggregators
Community discussions
Grey may use Tier C to discover opportunities, but stronger evidence should support the final FYP recommendation.

12. Step 5 — Real Problem Extraction
Grey analyzes the evidence and extracts actual industry pain points.
Grey should not copy the product of an existing company.
The reasoning process is:
Organization
→ Existing Product/Solution
→ Capability
→ Pain Point
→ Technical Problem
→ Student Opportunity
Example:
A company is developing autonomous maritime surveillance systems.
Grey should not recommend:
“Build an autonomous military vessel.”
Instead Grey extracts the underlying problem:
Large volumes of maritime movement data make unusual vessel behavior difficult to detect manually.
That becomes a student opportunity.

13. Step 6 — Grey Presents Real Problem Opportunities
Grey should show a small number of strong problem opportunities.
Preferably:
3–5 problems
rather than a long list.
Example for Navy:
Opportunity 1
Abnormal vessel movement detection
Opportunity 2
Predictive maintenance for vessel equipment
Opportunity 3
Vessel classification from maritime imagery
Opportunity 4
Port traffic congestion prediction
Opportunity 5
Search-and-rescue decision support
The goal is to reduce confusion and choice overload.

14. Evidence-Backed Problem Cards
Each opportunity should appear as a clear card.
Example:
Abnormal Vessel Movement Detection
Real-World Problem
Maritime operators must monitor large volumes of vessel movement data, making unusual behavior difficult to identify manually.
Evidence
Relevant companies, government initiatives, research, or industry sources.
Why It Matters
Improved maritime awareness can help identify unusual vessel behavior earlier.
Possible FYP Direction
Develop an AI-based system that identifies anomalous vessel trajectories from public AIS data.
View Sources
The student can inspect the original evidence.

15. Step 7 — Student Selects a Problem
The student selects the problem they find most interesting.
Example:
Abnormal Vessel Movement Detection
Once selected, Grey stores this as the chosen problem.
The discovery stage ends.
Grey should stop generating unrelated problems unless the student intentionally goes back.

16. Step 8 — Automatic Functional-Area Classification
After the problem is selected, Grey determines where the FYP belongs.
Example:
Your Project Area
Industry: Defense
Branch: Navy
Functional Area: Maritime Surveillance
Specific Area: Vessel Behavior Monitoring
Problem: Abnormal Vessel Movement Detection
This is better than requiring the student to know the functional area beforehand.
Grey teaches the student where their project sits after the problem becomes meaningful.

17. Step 9 — Grey Converts the Problem Into an FYP
Grey creates a student-sized project.
Example:
Proposed FYP
AI-Based Maritime Vessel Anomaly Detection Using AIS Data
Grey explains:
what the student will build,
who the intended user is,
what the input will be,
what output the system produces,
what the main contribution is.
The project should now be concrete enough to understand.

18. “Why This FYP?” Section
Grey should explain:
where the problem came from,
which organizations are solving related problems,
what the evidence shows,
why the problem matters,
how Grey reduced the real-world problem into a feasible student FYP.
This gives the student confidence and provides material for supervisor discussion.

19. Step 10 — Problem Definition
Grey creates a precise definition of the selected FYP.
The student should clearly understand:
What problem exists?
Who experiences the problem?
Why does it matter?
What currently exists?
What gap remains?
What exactly will the student build?
This becomes the foundation for the proposal.

20. Step 11 — Scope Definition
Grey defines the project scope.
Core Scope
Features that must be implemented.
Optional Scope
Features that may be added if time remains.
Out of Scope
Features that are intentionally excluded.
This protects the student from choosing an unrealistic project.

21. Step 12 — Proposed Solution
Grey defines the proposed system.
It should identify:
System purpose
Target user
Main modules
Input
Output
Core features
AI component
Non-AI components
Expected workflow
The student should understand what the final system will actually look like.

22. Step 13 — AI Necessity Check
Grey should first determine:
Does this problem actually need AI?
Possible outcomes:
AI is necessary
AI is useful but optional
Traditional ML is sufficient
A rule-based approach is better
Optimization is more appropriate
Existing model/API is sufficient
AI is not required
Grey should never force AI into the project.

23. Step 14 — AI / ML Strategy
If AI is appropriate, Grey identifies the technical task.
Examples:
Classification
Regression
Forecasting
Anomaly Detection
Computer Vision
Object Detection
NLP
Recommendation
Clustering
Time-Series Analysis
Retrieval
Generative AI
Grey then recommends one primary implementation strategy:
Train a model
Fine-tune an existing model
Use a pretrained model
Use an API
Use a hybrid approach
Grey may also provide one fallback strategy.

24. Step 15 — Dataset Discovery
Grey searches for datasets suitable for the project.
Possible sources:
Kaggle
UCI Machine Learning Repository
Hugging Face
Government open-data portals
Research repositories
GitHub
Public APIs
Industry open datasets
University repositories
Synthetic data
Student-collected data
Grey should preferably recommend:
Primary Dataset
and
Alternative Dataset
rather than overwhelming the student with many options.

25. Dataset Information
For each dataset, Grey should explain:
Dataset name
Source
Size
Main features
Labels
License
Relevance to the project
Required preprocessing
Limitations
Possible alternative
Grey should evaluate whether the dataset actually fits the selected problem.

26. Step 16 — Pretrained Models and APIs
Grey checks whether relevant models or APIs already exist.
Sources may include:
Hugging Face
PyTorch Hub
TensorFlow Hub
GitHub repositories
Research implementations
Cloud AI services
Public APIs
Grey explains whether the student should:
use the model directly,
fine-tune it,
use it as a benchmark,
or avoid it.

27. Step 17 — Technology Stack Guidance
Grey recommends a focused implementation stack.
Possible categories:
Frontend
React
Next.js
Flutter
Mobile
Dashboard framework
Backend
FastAPI
Django
Node.js
other appropriate framework
Database
PostgreSQL
MySQL
MongoDB
other suitable storage
AI/ML
Python
PyTorch
TensorFlow
Scikit-learn
task-specific libraries
Training
Local machine
Google Colab
Cloud GPU
Deployment
Local
Cloud
University infrastructure
Lightweight hosting
Grey should recommend what is needed rather than showing unnecessary alternatives.

28. Technology Recommendation Principle
Grey should explain:
Why this technology is suitable for this particular FYP.
Grey should avoid:
“You can use React, Vue, Angular, Next.js, Svelte…”
Instead:
“For this project, React is sufficient because the main frontend requirement is an interactive dashboard.”
Grey should prefer decisions over option overload.

29. Step 18 — Hardware and Infrastructure
Grey determines whether the project requires:
Normal laptop
Dedicated GPU
Google Colab
Cloud GPU
Camera
Sensors
Arduino
Raspberry Pi
Jetson
Mobile device
Other hardware
Grey should explain:
what is required,
estimated complexity/cost,
whether the hardware is essential,
possible alternatives.

30. Step 19 — System Architecture
Grey creates a high-level system architecture.
Example:
AIS Dataset
→ Data Preprocessing
→ Anomaly Detection Model
→ Backend API
→ Database
→ Dashboard
→ User
The architecture should be directly derived from the selected FYP.

31. Step 20 — Evaluation Plan
Grey determines how the student will prove that the system works.
Possible AI evaluation metrics may include:
Accuracy
Precision
Recall
F1-score
AUC
MAE
RMSE
False Alarm Rate
Detection Rate
Grey chooses metrics appropriate to the project.
The system may also require:
Functional testing
Usability testing
Response time
Baseline comparison
User evaluation
The evaluation strategy should be known before proposal generation.

32. Step 21 — Feasibility Analysis
Grey evaluates whether the FYP is realistic.
Important dimensions:
Problem relevance
Evidence strength
Data availability
Technical complexity
Hardware requirement
Cost
Time
Evaluation possibility
External dependencies
Ethical/legal concerns
Demonstrability
Risk
Novelty
Grey should return a simple result:
Feasibility
High / Medium / Low
with clear reasoning.
Example:
Evidence: Strong
Dataset: Available
Technical Difficulty: Moderate
Hardware: Low
Evaluation: Feasible
Main Risk: Dataset preprocessing
Overall Feasibility: High

33. Step 22 — Supervisor Readiness Check
Before the proposal is generated, Grey verifies:
Is the problem clear?
Is the problem supported by evidence?
Is the proposed contribution clear?
Is the dataset available?
Is the AI strategy justified?
Is the scope realistic?
Is the technology accessible?
Is evaluation possible?
Are the main risks understood?
If a major weakness exists, Grey should resolve it first.

34. Step 23 — Supervisor-Ready Summary
Grey generates a compact briefing containing:
Project Title
Industry
Functional Area
Real-World Problem
Evidence
Proposed Solution
Contribution
Dataset
AI/ML Strategy
Technology Stack
Architecture
Evaluation
Feasibility
Main Risks
This summary helps the student explain the project to the supervisor.

35. Step 24 — Likely Supervisor Questions
Grey prepares questions such as:
Why did you choose this problem?
What evidence proves the problem exists?
Who will use the system?
What already exists?
What is your contribution?
Why does the project require AI?
Where will the dataset come from?
How will the model be evaluated?
What are the limitations?
Is the project achievable within the FYP timeline?
Grey can provide recommended talking points for each question.

36. Step 25 — Proposal Generation
The final major output of Grey MVP is a complete FYP proposal.
The proposal should be generated from the Project Brain rather than from one large prompt.
Possible sections:
Project Title
Introduction
Background
Problem Statement
Motivation
Real-World Evidence
Proposed Solution
Aim
Objectives
Scope
Functional Requirements
Methodology
Dataset
AI/ML Approach
Technology Stack
System Architecture
Hardware Requirements
Evaluation Plan
Expected Outcomes
Risks
Limitations
Timeline
References

37. Proposal Traceability
The proposal should remain consistent with the decisions already made.
For example:
Problem Statement
comes from validated evidence.
Objectives
come from the selected project scope.
Methodology
comes from the AI and technical strategy.
Dataset Section
comes from dataset discovery.
Technology Stack
comes from implementation planning.
References
come from verified evidence sources.
This reduces hallucination and inconsistency.

38. Grey MVP Project Brain
The Project Brain should store the structured state of the FYP.
For the MVP, it needs:
Discovery State
Industry
Branch
Evidence
Candidate Problems
Selected Problem
Functional Area
FYP State
Project Title
Problem Statement
Target User
Proposed Solution
Contribution
Scope
Technical State
Dataset
Alternative Dataset
AI Requirement
AI Strategy
Model/API
Frontend
Backend
Database
Hardware
Architecture
Evaluation Plan
Validation State
Feasibility
Risks
Supervisor Readiness
Output State
Supervisor Summary
Proposal
The Project Brain is the source of truth.

39. Grey MVP State Machine
Internally, Grey should move through states such as:
START
↓
INDUSTRY_SELECTION
↓
BRANCH_SELECTION
↓
EVIDENCE_RESEARCH
↓
PROBLEM_OPTIONS
↓
PROBLEM_SELECTED
↓
AREA_CLASSIFICATION
↓
FYP_DESIGN
↓
SCOPE
↓
DATASET_DISCOVERY
↓
AI_STRATEGY
↓
TECHNOLOGY_PLAN
↓
ARCHITECTURE
↓
EVALUATION
↓
FEASIBILITY
↓
SUPERVISOR_READINESS
↓
PROPOSAL_GENERATION
↓
COMPLETE
Grey always knows the current state.

40. Controlled Flexibility
Students can still ask relevant questions during the workflow.
Example:
“Can I do this without AI?”
Grey answers the question without losing the selected problem.
Example:
“I don’t like these three problems.”
Grey remains in:
PROBLEM_OPTIONS
and finds alternatives.
The student can move within the workflow without turning Grey into an unrestricted chatbot.

41. UI / UX Principle
Wherever possible, Grey should provide structured UI choices.
Instead of only:
“What industry?”
show:
Choose Industry
[Healthcare]
[Defense]
[Finance]
[Agriculture]
[Education]
Instead of:
“Which problem do you want?”
show evidence-backed opportunity cards.
Chat remains available, but cards, buttons, progress indicators, and project state should drive the main journey.

42. Token and AI Cost Principle
Grey should not send the entire conversation to the model every time.
Each model call should contain only:
Current stage
Current user input
Relevant Project Brain state
Required evidence
Specific task
Example during dataset discovery:
Industry: Defense
Branch: Navy
Functional Area: Maritime Surveillance
Problem: Vessel anomaly detection
Project: AIS-based anomaly detection
Task: Identify suitable datasets
This is enough.
Grey should not resend the complete conversation history.

43. Do Not Use an LLM for Everything
Many steps should use deterministic application logic.
For example:
Defense → Navy
does not require an LLM.
Industry and branch taxonomies can be predefined.
Buttons and workflow state changes should be handled by normal software.
AI should be used where reasoning adds value.

44. High-Value AI Calls
The main AI-heavy tasks should be:
Evidence Analysis
Understand what organizations are solving.
Problem Extraction
Identify genuine pain points from sources.
FYP Generation
Convert a real problem into a student project.
Technical Planning
Determine datasets, AI strategy, stack, architecture, and evaluation.
Feasibility Analysis
Evaluate whether the FYP is realistic.
Proposal Generation
Convert the validated Project Brain into a structured academic proposal.
This keeps Grey more economical and predictable.

45. Grey Should Prefer Decisions Over Endless Conversations
Bad experience:
Student: Give me ideas.
Grey: Here are 20.
Student: More.
Grey: Here are another 20.
Good experience:
Choose Industry
↓
Choose Branch
↓
Grey researches real-world problems
↓
Choose one of 3–5 validated opportunities
↓
Grey designs the FYP
↓
Grey validates feasibility
↓
Generate Proposal
Grey should help the student move forward.

46. What Grey MVP Does NOT Need Initially
The first version does not need:
Full coding
Coding IDE
Automatic codebase generation
GitHub review
Full-year milestone tracking
Complete final report generation
Final defense mode
Detailed student skill matching
Long-term student personality profiling
Unlimited brainstorming
These can be future phases.

47. Complete Grey MVP Journey
Student says: “I need an FYP.”
↓
Grey asks for industry
↓
Student selects industry
↓
Grey asks for branch
↓
Student selects branch
↓
Grey researches real companies, startups, government initiatives, research, news, and datasets
↓
Grey extracts real pain points
↓
Grey shows 3–5 evidence-backed problems
↓
Student selects one problem
↓
Grey automatically determines the functional area
↓
Grey converts the problem into a student-sized FYP
↓
Grey defines the exact problem and proposed solution
↓
Grey defines project scope
↓
Grey checks whether AI is actually needed
↓
Grey selects the AI/ML approach
↓
Grey finds the primary and alternative datasets
↓
Grey identifies pretrained models/APIs where relevant
↓
Grey recommends the technical stack
↓
Grey identifies hardware/infrastructure
↓
Grey creates the system architecture
↓
Grey creates the evaluation plan
↓
Grey performs feasibility analysis
↓
Grey performs supervisor-readiness validation
↓
Grey generates a supervisor-ready project summary
↓
Grey generates the final FYP proposal
↓
MVP COMPLETE

48. Final Grey MVP Definition
Grey is a structured, evidence-driven AI FYP companion that takes a student from broad industry interest to a real-world problem, converts that problem into a feasible technical project, provides the resources and implementation plan needed to understand how it can be built, and produces a supervisor-ready FYP proposal.
The simplest description is:
Choose where you want to build → Grey finds real problems → choose a problem → Grey turns it into a feasible FYP → Grey shows how it can be built → Grey validates it → Grey generates the proposal.
