from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import base64

def encryption_check(dataString):
    if dataString.startswith("\$GNGGA"):
        return False
    return True

def decrypt_aes(ciphertext_b64, key, iv):
    # Decode the base64 encoded ciphertext
    ciphertext = base64.b64decode(ciphertext_b64)
    
    # Create AES cipher object
    cipher = AES.new(key, AES.MODE_CBC, iv)
    
    # Decrypt the ciphertext
    decrypted_padded = cipher.decrypt(ciphertext)
    
    # Unpad the decrypted data
    decrypted = unpad(decrypted_padded, AES.block_size)
    
    return decrypted.decode('utf-8')