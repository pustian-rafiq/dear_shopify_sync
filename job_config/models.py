from django.db import models
from base.models import BaseModel
import uuid
import base64
# Create your models here.
class JobConfiguration(BaseModel):
    config_name = models.CharField(db_column='config_name', max_length=50, blank=True, null=True)
    config_value = models.TextField(db_column='config_value', blank=True, null=True)
    
    def __str__(self):
        return str(self.config_name)
    
    def save(self, *args, **kwargs):
        #Encode the email password before saving
        if self.config_name == "EMAIL_HOST_PASSWORD" and self.config_value:
            try:
                self.config_value = base64.b64encode(self.config_value)
            except Exception as e:
                # If not encoded, encode it
                self.config_value = base64.b64encode(self.config_value.encode('utf-8')).decode('utf-8')
        super().save(*args, **kwargs)
    
    @property
    def decoded_email_password(self):
        # Only decode if this config_name is the encoded one
        if self.config_name == "EMAIL_HOST_PASSWORD" and self.config_value:
            try:
                return base64.b64decode(self.config_value).decode('utf-8')
            except Exception as e:
                return self.config_value
        return self.config_value

class AuthUserToken(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.TextField(db_column='token', blank=True, null=True)
    provider = models.CharField(db_column='provider', max_length=50, blank=True, null=True)
    token_creation_time = models.DateTimeField(db_column='token_creation_time', auto_now_add=True)
    expire_time = models.IntegerField(db_column='expire_time', blank=True, null=True)
    
    def __str__(self):
        return str(self.id)
    