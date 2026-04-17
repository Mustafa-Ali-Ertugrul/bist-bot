package com.bistbot;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

public class BistBotActivity extends AppCompatActivity {

    private static final String TAG = "BistBotActivity";

    private WebView webView;
    private ProgressBar loadingIndicator;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webView);
        loadingIndicator = findViewById(R.id.loadingIndicator);
        configureWebView();

        String startupUrl = Constants.BIST_BOT_URL;
        Log.d(TAG, "Startup URL: " + startupUrl);
        webView.loadUrl(startupUrl);
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        }

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            cookieManager.setAcceptThirdPartyCookies(webView, true);
        }

        webView.addJavascriptInterface(new WebAppInterface(this), "Android");
        webView.setWebViewClient(new AppWebViewClient());
    }

    private boolean isInternalUrl(String url) {
        return url != null && url.startsWith(Constants.BIST_BOT_URL);
    }

    private class AppWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            String safeUrl = Constants.guardWest1Redirect(url);

            if (Constants.isWest1Url(url)) {
                Log.w(TAG, "West1 redirect blocked: " + url + " -> " + safeUrl);
            }

            if (isInternalUrl(safeUrl)) {
                return false;
            }

            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(safeUrl)));
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            super.onPageStarted(view, url, favicon);
            if (loadingIndicator != null) {
                loadingIndicator.setVisibility(android.view.View.VISIBLE);
            }
            Log.d(TAG, "Page started: " + url);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            if (loadingIndicator != null) {
                loadingIndicator.setVisibility(android.view.View.GONE);
            }
            Log.d(TAG, "Page finished: " + url);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                if (loadingIndicator != null) {
                    loadingIndicator.setVisibility(android.view.View.GONE);
                }
                CharSequence description = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                    ? error.getDescription()
                    : "Unknown error";
                Log.e(TAG, "WebView error: " + description);
            }
        }
    }

    public static class WebAppInterface {
        private final Context context;

        WebAppInterface(Context context) {
            this.context = context;
        }

        @JavascriptInterface
        public void showToast(String message) {
            Toast.makeText(context, message, Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
