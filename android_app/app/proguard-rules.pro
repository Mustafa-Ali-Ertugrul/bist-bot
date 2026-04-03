# WebView
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
-keep public class com.bistbot.MainActivity$WebAppInterface
-keep public class * implements com.bistbot.MainActivity$WebAppInterface

# Keep notification-related classes
-keep class com.bistbot.MarketOpenReceiver { *; }
-keepclassmembers class com.bistbot.MarketOpenReceiver { *; }
