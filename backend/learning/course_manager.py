from __future__ import annotations

from copy import deepcopy


LEVELS = [
    {"id": "beginner", "title": "Beginner", "order": 1},
    {"id": "intermediate", "title": "Intermediate", "order": 2},
    {"id": "advanced", "title": "Advanced", "order": 3},
    {"id": "professional", "title": "Professional / Job Ready", "order": 4},
]


TOPICS = [
    {
        "id": "python",
        "title": "Python",
        "role": "Python Developer",
        "weeks": 12,
        "docs": "https://docs.python.org/3/",
        "practice": "https://www.hackerrank.com/domains/python",
        "github": "https://github.com/search?q=python+projects&type=repositories",
        "book": "Automate the Boring Stuff with Python",
        "certification": "PCEP / PCAP Python certification",
        "base_lessons": [
            "Execution model and syntax",
            "Control flow and functions",
            "Lists, tuples, sets, and dictionaries",
            "Strings, files, and paths",
            "Exceptions and debugging",
            "Object-oriented Python",
            "Modules, packages, and environments",
            "Testing and quality",
            "APIs and automation",
            "Portfolio project delivery",
        ],
    },
    {
        "id": "data-science",
        "title": "Data Science",
        "role": "Data Scientist",
        "weeks": 14,
        "docs": "https://pandas.pydata.org/docs/",
        "practice": "https://www.kaggle.com/learn",
        "github": "https://github.com/search?q=data+science+portfolio&type=repositories",
        "book": "Python for Data Analysis",
        "certification": "Google Data Analytics / IBM Data Science",
        "base_lessons": [
            "Problem framing and datasets",
            "Pandas workflow",
            "Data cleaning and validation",
            "Exploratory data analysis",
            "Statistics for decisions",
            "Visualization and storytelling",
            "SQL analytics",
            "Feature preparation",
            "Insight communication",
            "Portfolio case study",
        ],
    },
    {
        "id": "machine-learning",
        "title": "Machine Learning",
        "role": "Machine Learning Engineer",
        "weeks": 16,
        "docs": "https://scikit-learn.org/stable/user_guide.html",
        "practice": "https://www.kaggle.com/competitions",
        "github": "https://github.com/search?q=machine+learning+projects&type=repositories",
        "book": "Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow",
        "certification": "AWS Machine Learning Specialty / Google Professional ML Engineer",
        "base_lessons": [
            "ML problem framing",
            "Train validation test splits",
            "Regression models",
            "Classification models",
            "Feature pipelines",
            "Model evaluation",
            "Overfitting and regularization",
            "Unsupervised learning",
            "Deployment patterns",
            "Monitoring and MLOps",
        ],
    },
    {
        "id": "ai-engineering",
        "title": "AI Engineering",
        "role": "AI Engineer",
        "weeks": 16,
        "docs": "https://platform.openai.com/docs",
        "practice": "https://github.com/openai/openai-cookbook",
        "github": "https://github.com/search?q=ai+engineering+llm+app&type=repositories",
        "book": "Designing Machine Learning Systems",
        "certification": "Azure AI Engineer / Google Cloud Generative AI",
        "base_lessons": [
            "AI product architecture",
            "LLM API fundamentals",
            "Structured outputs",
            "Tool calling",
            "Agents and workflows",
            "Evaluation systems",
            "Memory and personalization",
            "Streaming user experience",
            "Safety and guardrails",
            "Deployment and scaling",
        ],
    },
    {
        "id": "rag",
        "title": "RAG Engineering",
        "role": "RAG Engineer",
        "weeks": 12,
        "docs": "https://python.langchain.com/docs/",
        "practice": "https://github.com/search?q=rag+retrieval+augmented+generation&type=repositories",
        "github": "https://github.com/search?q=production+rag&type=repositories",
        "book": "AI Engineering",
        "certification": "Vector database and LLM application certifications",
        "base_lessons": [
            "RAG mental model",
            "Document ingestion",
            "Chunking strategy",
            "Embeddings and indexes",
            "Hybrid retrieval",
            "Reranking",
            "Grounded answer generation",
            "RAG evaluation",
            "RAG security",
            "Production observability",
        ],
    },
    {
        "id": "prompt-engineering",
        "title": "Prompt Engineering",
        "role": "Prompt Engineer",
        "weeks": 10,
        "docs": "https://platform.openai.com/docs/guides/prompt-engineering",
        "practice": "https://www.promptingguide.ai/",
        "github": "https://github.com/search?q=prompt+engineering&type=repositories",
        "book": "The Prompt Engineering Guide",
        "certification": "Generative AI prompt engineering certificates",
        "base_lessons": [
            "Prompt anatomy",
            "Instruction hierarchy",
            "Context management",
            "Few-shot examples",
            "Output schemas",
            "Reasoning controls",
            "Prompt evaluation",
            "Safety prompts",
            "Reusable prompt patterns",
            "Prompt systems",
        ],
    },
    {
        "id": "mechanical-design",
        "title": "Mechanical Design Engineering",
        "role": "Mechanical Design Engineer",
        "weeks": 14,
        "docs": "https://help.solidworks.com/",
        "practice": "https://grabcad.com/challenges",
        "github": "https://github.com/search?q=mechanical+design+engineering&type=repositories",
        "book": "Shigley's Mechanical Engineering Design",
        "certification": "CSWA / CSWP / GD&T certification",
        "base_lessons": [
            "Design requirements",
            "Load paths and free body diagrams",
            "Materials selection",
            "CAD modeling strategy",
            "Tolerances and fits",
            "Fasteners and joints",
            "Design for manufacturing",
            "FEA basics",
            "Prototyping and testing",
            "Design reviews",
        ],
    },
]


def _code_example(topic: dict, lesson: str, level: dict) -> str:
    if topic["id"] == "mechanical-design":
        return "Engineering calculation card: define load case, assumptions, material, safety factor, tolerance stack, and inspection method."
    if topic["id"] == "prompt-engineering":
        return f"Prompt template: Role -> Goal -> Context -> Constraints -> Output schema -> Examples for {lesson}."
    if topic["id"] == "rag":
        return "Python sketch: retrieve(query) -> rerank(chunks) -> answer_with_citations(query, context)."
    if topic["id"] == "ai-engineering":
        return "API sketch: validate request, call model, run tool, store trace, return structured result."
    if topic["id"] == "machine-learning":
        return "sklearn sketch: Pipeline([preprocess, model]).fit(X_train, y_train); evaluate on validation set."
    if topic["id"] == "data-science":
        return "pandas sketch: df.groupby(segment).agg(metric=('value','mean')).reset_index()."
    return "Python sketch: def solve(input_data): validate, transform, test edge cases, return result."


def _lesson(topic: dict, level: dict, index: int, lesson_title: str) -> dict:
    level_title = level["title"]
    duration = 18 + (index % 5) * 6 + level["order"] * 3
    difficulty = level_title
    lesson_id = f"{topic['id']}-{level['id']}-{index + 1}"
    core = f"{lesson_title} in {topic['title']}"
    return {
        "id": lesson_id,
        "title": lesson_title,
        "level": level_title,
        "difficulty": difficulty,
        "minutes": duration,
        "duration": f"{duration} min",
        "content": f"{core} teaches the mental model, workflow, tradeoffs, and practical execution expected at the {level_title.lower()} level.",
        "explanation": f"Start with the why, then learn the process. For {core}, focus on inputs, constraints, decisions, validation, and how a professional would explain the outcome.",
        "key_concepts": [
            f"{lesson_title} fundamentals",
            f"{topic['title']} workflow",
            "Quality checks",
            "Tradeoffs",
            "Communication",
        ],
        "diagram": {
            "title": f"{lesson_title} flow",
            "description": "Concept map: inputs -> decisions -> practice -> feedback -> portfolio artifact.",
        },
        "visual_card": {
            "title": f"{level_title} focus",
            "description": f"Use this lesson to move from knowing {lesson_title.lower()} to applying it in a realistic {topic['role']} scenario.",
        },
        "examples": [
            f"Simple example: explain {lesson_title.lower()} to a teammate.",
            f"Applied example: use {lesson_title.lower()} in a small project.",
        ],
        "practical_examples": [
            f"Build a one-page artifact showing {lesson_title.lower()} decisions.",
            f"Review a failed project and identify how {lesson_title.lower()} would improve it.",
        ],
        "code_examples": [_code_example(topic, lesson_title, level)],
        "industry_examples": [
            f"A {topic['role']} uses {lesson_title.lower()} to reduce risk before delivery.",
            f"Teams document {lesson_title.lower()} decisions during reviews and interviews.",
        ],
        "common_mistakes": [
            "Jumping to tools before defining the problem",
            "Skipping validation",
            "Not explaining tradeoffs",
        ],
        "best_practices": [
            "Write assumptions explicitly",
            "Use small tests or checks",
            "Document decisions in plain language",
        ],
        "mini_project": f"Create a {level_title.lower()} mini project demonstrating {lesson_title.lower()} for {topic['title']}.",
        "challenge_task": f"Apply {lesson_title.lower()} to a messy real-world scenario and explain your tradeoffs.",
        "summary": f"You should now be able to explain, apply, test, and discuss {lesson_title.lower()} at the {level_title.lower()} level.",
        "practice": [
            {
                "id": f"{lesson_id}-practice-1",
                "question": f"Create a practical example that proves you understand {lesson_title}.",
                "answer": f"A strong answer includes context, constraints, method, result, and a validation check for {lesson_title}.",
                "hint": "Use a real project or workplace-style scenario.",
                "difficulty": level_title,
            },
            {
                "id": f"{lesson_id}-practice-2",
                "question": f"What failure mode appears when {lesson_title} is ignored?",
                "answer": "The project becomes harder to validate, explain, maintain, or trust.",
                "hint": "Think about quality, cost, time, and risk.",
                "difficulty": level_title,
            },
        ],
        "question_bank": [
            {
                "id": f"{lesson_id}-q-beginner",
                "type": "Beginner",
                "question": f"What is {lesson_title}?",
                "answer": f"{lesson_title} is a core skill used to structure decisions in {topic['title']}.",
                "explanation": "Define the concept first, then attach it to a practical outcome.",
                "hint": "Use one sentence plus one example.",
                "difficulty": "Beginner",
            },
            {
                "id": f"{lesson_id}-q-intermediate",
                "type": "Intermediate",
                "question": f"How would you apply {lesson_title} in a project?",
                "answer": "Define inputs, constraints, approach, validation, and communication output.",
                "explanation": "Intermediate answers show process, not just vocabulary.",
                "hint": "Mention a project artifact.",
                "difficulty": "Intermediate",
            },
            {
                "id": f"{lesson_id}-q-advanced",
                "type": "Advanced",
                "question": f"What tradeoff matters most for {lesson_title}?",
                "answer": "The key tradeoff is usually speed versus reliability, cost versus quality, or simplicity versus flexibility.",
                "explanation": "Advanced answers compare options and risks.",
                "hint": "Name two options and when each wins.",
                "difficulty": "Advanced",
            },
            {
                "id": f"{lesson_id}-q-interview",
                "type": "Interview",
                "question": f"Tell me about a time you used {lesson_title}.",
                "answer": "Use STAR: situation, task, action, result, and what you improved.",
                "explanation": "Interview answers need evidence, not just theory.",
                "hint": "Quantify the result if possible.",
                "difficulty": "Professional / Job Ready",
            },
            {
                "id": f"{lesson_id}-q-scenario",
                "type": "Real-world scenario",
                "question": f"A project using {lesson_title} is failing. What do you do first?",
                "answer": "Clarify expected outcome, inspect assumptions, isolate the failing step, and propose a small validated fix.",
                "explanation": "Real-world scenarios reward triage and communication.",
                "hint": "Start by narrowing the failure.",
                "difficulty": level_title,
            },
        ],
        "quiz": [
            {
                "id": f"{lesson_id}-mcq",
                "type": "MCQ",
                "question": f"What is the best first step for {lesson_title}?",
                "choices": ["Define the problem and constraints", "Skip validation", "Use the newest tool", "Ignore user needs"],
                "answer": "Define the problem and constraints",
                "explanation": "Good work starts with clear constraints and success criteria.",
            },
            {
                "id": f"{lesson_id}-case",
                "type": "Case Study",
                "question": f"Choose the strongest case-study response for {lesson_title}.",
                "choices": ["State assumptions, method, result, and risk", "Only list tools", "Only give definitions", "Avoid tradeoffs"],
                "answer": "State assumptions, method, result, and risk",
                "explanation": "Case-study answers must show professional judgment.",
            },
            {
                "id": f"{lesson_id}-interview",
                "type": "Interview",
                "question": f"What makes an interview answer about {lesson_title} strong?",
                "choices": ["Concrete example and measured outcome", "A vague claim", "Memorized terms only", "No follow-up"],
                "answer": "Concrete example and measured outcome",
                "explanation": "Strong interview answers prove impact.",
            },
        ],
        "coding_lab": {
            "title": f"{lesson_title} lab",
            "difficulty": level_title,
            "starter_code": _code_example(topic, lesson_title, level),
            "solution": f"Complete the lab by implementing the workflow, validating one edge case, and writing a short explanation for {lesson_title}.",
            "explanation": "The lab converts theory into a reusable portfolio artifact.",
        },
        "resources": {
            "official_documentation": topic["docs"],
            "youtube_search": f"https://www.youtube.com/results?search_query={topic['title'].replace(' ', '+')}+{lesson_title.replace(' ', '+')}",
            "github_repositories": topic["github"],
            "practice_websites": topic["practice"],
            "recommended_books": [topic["book"]],
            "certifications": [topic["certification"]],
        },
        "interview": {
            "question": f"How would you explain {lesson_title} to a hiring manager?",
            "short_answer": f"It helps a {topic['role']} make better decisions in {topic['title']}.",
            "detailed_answer": f"I would explain the concept, show where it appears in a project, describe tradeoffs, and prove it with a tested artifact.",
            "professional_answer": f"In production, I use {lesson_title.lower()} to align requirements, implementation, validation, and communication so the team can trust the result.",
            "follow_up": f"What metric or review would you use to validate {lesson_title}?",
            "answer": f"A professional answer connects {lesson_title} to decisions, tradeoffs, and measurable outcomes.",
        },
    }


def _course(topic: dict, level: dict) -> dict:
    lessons = [_lesson(topic, level, index, title) for index, title in enumerate(topic["base_lessons"])]
    return {
        "id": f"{topic['id']}-{level['id']}",
        "path_id": topic["id"],
        "level": level["title"],
        "title": f"{topic['title']} - {level['title']}",
        "description": f"{topic['title']} learning track for {level['title'].lower()} learners moving toward {topic['role']} readiness.",
        "duration": f"{len(lessons)} lessons",
        "skill_score": min(100, 20 + level["order"] * 16),
        "lessons": lessons,
        "resources": lessons[0]["resources"],
    }


LEARNING_PATHS = [
    {
        "id": topic["id"],
        "title": topic["title"],
        "level": "Beginner to Professional",
        "weeks": topic["weeks"],
        "role": topic["role"],
    }
    for topic in TOPICS
]

COURSES = [_course(topic, level) for topic in TOPICS for level in LEVELS]


def get_paths() -> list[dict]:
    return deepcopy(LEARNING_PATHS)


def get_courses(path_id: str | None = None) -> list[dict]:
    courses = deepcopy(COURSES)
    if path_id:
        courses = [course for course in courses if course["path_id"] == path_id]
    return courses


def get_course(course_id: str) -> dict | None:
    for course in COURSES:
        if course["id"] == course_id:
            return deepcopy(course)
    return None