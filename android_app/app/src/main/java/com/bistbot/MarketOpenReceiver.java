package com.bistbot;

import android.app.AlarmManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;
import androidx.core.app.NotificationCompat;
import java.util.Arrays;
import java.util.Calendar;
import java.util.HashSet;
import java.util.Set;

public class MarketOpenReceiver extends BroadcastReceiver {
    private static final String TAG = "BISTBot";
    private static final String CHANNEL_ID = "bist_bot_notifications";
    public static final String ACTION_DISMISS = "com.bistbot.DISMISS_NOTIFICATION";

    private static final Set<String> TURKISH_HOLIDAYS_2024 = new HashSet<>(Arrays.asList(
        "01-01", "01-02",
        "04-10", "04-11", "04-12", "04-13", "04-14",
        "05-01", "05-19",
        "06-15", "06-16", "06-17", "06-18", "06-19",
        "07-15",
        "08-30",
        "10-28", "10-29"
    ));

    private static final Set<String> TURKISH_HOLIDAYS_2025 = new HashSet<>(Arrays.asList(
        "01-01",
        "03-30", "03-31", "04-01", "04-02",
        "05-01", "05-19",
        "06-05", "06-06", "06-07", "06-08",
        "07-15",
        "08-30",
        "10-28", "10-29"
    ));

    private static final Set<String> TURKISH_HOLIDAYS_2026 = new HashSet<>(Arrays.asList(
        "01-01",
        "03-19", "03-20", "03-21", "03-22",
        "05-01", "05-19",
        "05-25", "05-26", "05-27", "05-28",
        "07-15",
        "08-30",
        "10-28", "10-29"
    ));

    @Override
    public void onReceive(Context context, Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            scheduleNextAlarm(context);
            return;
        }

        if (ACTION_DISMISS.equals(intent.getAction())) {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            nm.cancel(100);
            nm.cancel(101);
            return;
        }

        Calendar calendar = Calendar.getInstance();
        int dayOfWeek = calendar.get(Calendar.DAY_OF_WEEK);
        int hour = calendar.get(Calendar.HOUR_OF_DAY);

        if (isTradingDay(calendar)) {
            if (hour == 10) {
                showNotification(context, 100,
                        context.getString(R.string.market_open_title),
                        context.getString(R.string.market_open_text));
            } else if (hour == 18) {
                showNotification(context, 101,
                        context.getString(R.string.market_close_title),
                        context.getString(R.string.market_close_text));
            } else if (hour > 10 && hour < 18) {
                showNotification(context, 102,
                        context.getString(R.string.market_tracking_title),
                        String.format(context.getString(R.string.market_tracking_text), hour));
            }
        }

        scheduleNextAlarm(context);
    }

    private boolean isTradingDay(Calendar calendar) {
        int dayOfWeek = calendar.get(Calendar.DAY_OF_WEEK);
        if (dayOfWeek == Calendar.SATURDAY || dayOfWeek == Calendar.SUNDAY) {
            return false;
        }

        String dateKey = String.format("%02d-%02d",
                calendar.get(Calendar.MONTH) + 1,
                calendar.get(Calendar.DAY_OF_MONTH));

        int year = calendar.get(Calendar.YEAR);
        Set<String> holidays;
        switch (year) {
            case 2024: holidays = TURKISH_HOLIDAYS_2024; break;
            case 2025: holidays = TURKISH_HOLIDAYS_2025; break;
            case 2026: holidays = TURKISH_HOLIDAYS_2026; break;
            default: return true;
        }

        if (holidays.contains(dateKey)) {
            Log.d(TAG, "Market closed on holiday: " + dateKey);
            return false;
        }

        return true;
    }

    public static void scheduleNextAlarm(Context context) {
        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        Intent intent = new Intent(context, MarketOpenReceiver.class);

        PendingIntent pendingIntent = PendingIntent.getBroadcast(
                context, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0)
        );

        Calendar calendar = Calendar.getInstance();
        int currentHour = calendar.get(Calendar.HOUR_OF_DAY);

        if (currentHour < 10) {
            calendar.set(Calendar.HOUR_OF_DAY, 10);
            calendar.set(Calendar.MINUTE, 0);
        } else if (currentHour < 18) {
            calendar.add(Calendar.HOUR_OF_DAY, 1);
            calendar.set(Calendar.MINUTE, 0);
        } else {
            calendar.add(Calendar.DAY_OF_YEAR, 1);
            calendar.set(Calendar.HOUR_OF_DAY, 10);
            calendar.set(Calendar.MINUTE, 0);
        }

        calendar.set(Calendar.SECOND, 0);
        calendar.set(Calendar.MILLISECOND, 0);

        int dayOfWeek = calendar.get(Calendar.DAY_OF_WEEK);
        if (dayOfWeek == Calendar.SATURDAY) {
            calendar.add(Calendar.DAY_OF_YEAR, 2);
        } else if (dayOfWeek == Calendar.SUNDAY) {
            calendar.add(Calendar.DAY_OF_YEAR, 1);
        }

        if (alarmManager != null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, calendar.getTimeInMillis(), pendingIntent);
            } else {
                alarmManager.setExact(AlarmManager.RTC_WAKEUP, calendar.getTimeInMillis(), pendingIntent);
            }
        }
    }

    private void showNotification(Context context, int id, String title, String text) {
        NotificationManager notificationManager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "BIST Bot Bildirimleri", NotificationManager.IMPORTANCE_HIGH);
            notificationManager.createNotificationChannel(channel);
        }

        Intent openIntent = new Intent(context, BistBotActivity.class);
        openIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        PendingIntent openPendingIntent = PendingIntent.getActivity(
                context, id, openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0)
        );

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.app_icon)
                .setContentTitle(title)
                .setContentText(text)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(openPendingIntent);

        notificationManager.notify(id, builder.build());
    }
}
