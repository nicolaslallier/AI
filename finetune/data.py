def to_messages(question, system_prompt="", answer=None):
    """Format de chat unique : l'entraînement (avec `answer`) et l'inférence (sans) doivent coïncider."""
    msgs = [{"role": "system", "content": system_prompt}] if system_prompt else []
    msgs.append({"role": "user", "content": question})
    if answer is not None:
        msgs.append({"role": "assistant", "content": answer})
    return msgs
