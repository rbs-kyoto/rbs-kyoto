from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import check_password, make_password

class User(AbstractUser):
    display_name = models.CharField(
        max_length = 100,
        blank = True
    )


class SuperuserGrantCredential(models.Model):
    password_hash = models.CharField("パスワードハッシュ", max_length=256, editable=False)

    class Meta:
        verbose_name = "スーパーユーザー昇格パスワード"
        verbose_name_plural = "スーパーユーザー昇格パスワード"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)