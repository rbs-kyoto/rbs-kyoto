import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from pywebpush import WebPushException
from requests import RequestException

from accounts.models import WebPushSubscription
from accounts.push import PushConfigurationError, send_web_push
from .models import News


logger = logging.getLogger(__name__)


@receiver(pre_save, sender=News)
def remember_previous_news_visibility(instance, **kwargs):
    if kwargs.get("raw", False):
        return
    instance._was_public = False
    if instance.pk:
        instance._was_public = News.objects.filter(
            pk=instance.pk,
            is_active=True,
            is_internal=False,
        ).exists()


@receiver(post_save, sender=News)
def notify_subscribers_of_new_public_news(instance, created, **kwargs):
    if kwargs.get("raw", False):
        return
    is_public = instance.is_active and not instance.is_internal
    if not is_public or (not created and instance._was_public):
        return
    transaction.on_commit(
        lambda news_id=instance.pk: send_news_notifications(news_id)
    )


def send_news_notifications(news_id):
    news = News.objects.filter(
        pk=news_id,
        is_active=True,
        is_internal=False,
    ).first()
    if news is None:
        return

    subscriptions = WebPushSubscription.objects.filter(
        news_notifications_enabled=True
    )
    for subscription in subscriptions.iterator():
        try:
            send_web_push(
                subscription,
                {
                    "title": "新しいお知らせが投稿されました",
                    "body": news.title,
                    "url": reverse("main:news_detail", args=[news.pk]),
                },
            )
        except PushConfigurationError:
            logger.exception(
                "Could not send new-news notification: Web Push is not configured."
            )
            break
        except (WebPushException, RequestException):
            logger.exception(
                "Could not send new-news notification to subscription %s.",
                subscription.pk,
            )
