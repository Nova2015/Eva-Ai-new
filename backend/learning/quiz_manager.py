from __future__ import annotations

from .course_manager import get_course


def submit_quiz(course_id: str, lesson_id: str, answers: dict[str, str]) -> dict:
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object keyed by question id")

    course = get_course(course_id)
    if not course:
        raise ValueError("course not found")

    lesson = next((item for item in course.get("lessons", []) if item["id"] == lesson_id), None)
    if not lesson:
        raise ValueError("lesson not found")

    questions = lesson.get("quiz", [])
    if not questions:
        return {"score": 100, "correct": 0, "total": 0, "results": []}

    results = []
    correct = 0
    for question in questions:
        submitted = str(answers.get(question["id"], "")).strip()
        expected = str(question["answer"]).strip()
        is_correct = submitted.lower() == expected.lower()
        correct += 1 if is_correct else 0
        results.append({
            "question_id": question["id"],
            "type": question.get("type", "MCQ"),
            "question": question["question"],
            "submitted": submitted,
            "answer": expected,
            "correct": is_correct,
            "explanation": question.get("explanation", ""),
            "hint": question.get("hint", ""),
            "difficulty": question.get("difficulty", lesson.get("difficulty", "")),
        })

    return {
        "score": round((correct / len(questions)) * 100),
        "correct": correct,
        "total": len(questions),
        "results": results,
    }