from cryptography.fernet import Fernet


class EncryptionGuard:

    def __init__(self):

        self.key = Fernet.generate_key()

        self.cipher = Fernet(self.key)

    # ENCRYPT
    def encrypt_data(

        self,
        data
    ):

        encrypted = self.cipher.encrypt(
            data.encode()
        )

        return encrypted.decode()

    # DECRYPT
    def decrypt_data(

        self,
        encrypted_data
    ):

        decrypted = self.cipher.decrypt(
            encrypted_data.encode()
        )

        return decrypted.decode()

    # GET KEY
    def get_key(self):

        return self.key.decode()


# TEST
if __name__ == "__main__":

    guard = EncryptionGuard()

    encrypted = guard.encrypt_data(
        "AWS_SECRET_KEY"
    )

    print("Encrypted:", encrypted)

    decrypted = guard.decrypt_data(
        encrypted
    )

    print("Decrypted:", decrypted)