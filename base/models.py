from django.db import models
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class BaseModel(models.Model):
    created_at = models.DateTimeField(db_column='created_at', auto_now_add=True)
    updated_at = models.DateTimeField(db_column='updated_at', auto_now=True)
    updated_by = models.ForeignKey(User, db_column='updated_by', on_delete=models.SET_NULL, null=True, blank=True, related_name='%(app_label)s_%(class)s_modified_by')
    created_by = models.ForeignKey(User, db_column='created_by', on_delete=models.SET_NULL, null=True, blank=True, related_name='%(app_label)s_%(class)s_created_by')
    # active_status = models.BooleanField(default=True, db_column='active_status',)

    class Meta:
        abstract = True