from __future__ import annotations

from .course_manager import TOPICS


def _questions(topic: dict) -> list[dict]:
    title = topic["title"]
    role = topic["role"]
    return [
        {
            "id": f"{topic['id']}-hr-1",
            "category": "HR",
            "question": f"Why do you want to work as a {role}?",
            "short_answer": f"I enjoy solving practical problems with {title} and turning ideas into useful outcomes.",
            "detailed_answer": f"I have been building skills in {title}, documenting projects, and learning how to communicate tradeoffs clearly.",
            "professional_answer": f"My motivation is to combine technical depth in {title} with reliable delivery, stakeholder communication, and continuous learning.",
            "follow_up": "Which project best proves that motivation?",
            "answer": f"Connect motivation to a concrete {title} project and measurable improvement.",
        },
        {
            "id": f"{topic['id']}-technical-1",
            "category": "Technical",
            "question": f"What is the most important technical tradeoff in {title}?",
            "short_answer": "The key tradeoff is balancing speed, reliability, quality, and maintainability.",
            "detailed_answer": f"In {title}, a strong answer explains the options, constraints, validation plan, and operational risk.",
            "professional_answer": f"I would choose the simplest approach that meets requirements, validate it with tests or review, and document why it can scale.",
            "follow_up": "How would you validate your choice?",
            "answer": "Name the tradeoff, compare options, and explain validation.",
        },
        {
            "id": f"{topic['id']}-behavioral-1",
            "category": "Behavioral",
            "question": f"Tell me about a time you improved a {title} project.",
            "short_answer": "Use STAR: situation, task, action, result.",
            "detailed_answer": "Describe the original issue, what you changed, how you measured success, and what you learned.",
            "professional_answer": f"I identified the highest-risk bottleneck, made a focused improvement, validated the result, and shared the learning with the team.",
            "follow_up": "What would you do differently next time?",
            "answer": "Use a concrete story with measured impact.",
        },
        {
            "id": f"{topic['id']}-scenario-1",
            "category": "Scenario",
            "question": f"A {title} deliverable is failing close to deadline. What do you do?",
            "short_answer": "Triage, communicate, isolate the failure, and deliver a safe fix.",
            "detailed_answer": "Clarify user impact, reproduce the issue, identify the smallest reliable fix, and document remaining risk.",
            "professional_answer": "I would protect users first, align stakeholders on scope, ship a validated mitigation, and schedule root-cause cleanup.",
            "follow_up": "How do you decide what not to fix immediately?",
            "answer": "Prioritize user impact, reversibility, and evidence.",
        },
    ]


def get_interview_prep() -> dict:
    return {
        "tracks": [
            {
                "id": f"{topic['id']}-interview",
                "path_id": topic["id"],
                "title": f"{topic['title']} Interview Prep",
                "questions": _questions(topic),
            }
            for topic in TOPICS
        ],
        "daily_drill": [
            "Answer one HR question using STAR.",
            "Solve one technical question out loud.",
            "Practice one real-world scenario question.",
            "Ask EVA to grade one answer and improve it.",
        ],
    }
