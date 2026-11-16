import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from pywebpush import WebPushException
from requests import RequestException

from accounts.audience import Audience
from accounts.models import NotificationHistory, WebPushSubscription
from accounts.push import PushConfigurationError, record_notification, send_web_push
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
            visibility=Audience.PUBLIC,
        ).exists()


@receiver(post_save, sender=News)
def notify_subscribers_of_new_public_news(instance, created, **kwargs):
    if kwargs.get("raw", False):
        return
    # 通知は誰にでも届きうるので、校外まで公開のお知らせだけを対象にする
    if not instance.is_public or (not created and instance._was_public):
        return
    transaction.on_commit(
        lambda news_id=instance.pk: send_news_notifications(news_id)
    )


def send_news_notifications(news_id):
    news = News.objects.filter(
        pk=news_id,
        is_active=True,
        visibility=Audience.PUBLIC,
    ).first()
    if news is None:
        return

    subscriptions = WebPushSubscription.objects.filter(
        news_notifications_enabled=True
    )
    payload = {
        "title": "新しいお知らせが投稿されました",
        "body": news.title,
        "url": reverse("main:news_detail", args=[news.pk]),
    }
    recorded_user_ids = set()
    for subscription in subscriptions.iterator():
        try:
            delivered = send_web_push(subscription, payload)
            if delivered and subscription.user_id not in recorded_user_ids:
                record_notification(
                    subscription.user_id, NotificationHistory.Kind.NEWS, payload
                )
                recorded_user_ids.add(subscription.user_id)
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
