# src/security/secure_memory.py

from datetime import datetime


class SecureMemory:

    def __init__(self):

        self.memory_store = {}

    # SAVE MEMORY
    def save(

        self,
        user_id,
        data
    ):

        if user_id not in self.memory_store:

            self.memory_store[user_id] = []

        self.memory_store[user_id].append({

            "timestamp": str(datetime.utcnow()),

            "data": data
        })

        return {

            "success": True,

            "message": "Memory saved securely"
        }

    # GET MEMORY
    def get(

        self,
        user_id
    ):

        return self.memory_store.get(
            user_id,
            []
        )

    # CLEAR MEMORY
    def clear(

        self,
        user_id
    ):

        if user_id in self.memory_store:

            del self.memory_store[user_id]

        return {

            "success": True,

            "message": "Memory cleared"
        }


# TEST
if __name__ == "__main__":

    memory = SecureMemory()

    memory.save(

        "admin",

        "Cloud security discussion"
    )

    result = memory.get("admin")

    print(result)