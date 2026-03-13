package com.bistbot;

import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;

public class MainActivity extends Activity {
    private WebView webView;
    private LinearLayout splashContainer;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        webView = findViewById(R.id.webView);
        splashContainer = findViewById(R.id.splashContainer);
        
        WebSettings webSettings = webView.getSettings();
        webSettings.setJavaScriptEnabled(true);
        webSettings.setDomStorageEnabled(true);
        webSettings.setAllowFileAccess(true);
        webSettings.setCacheMode(WebSettings.LOAD_DEFAULT);
        
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                // Sayfa yüklendiğinde splash ekranını gizle ve webview'ı göster
                new Handler().postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        splashContainer.setVisibility(View.GONE);
                        webView.setVisibility(View.VISIBLE);
                    }
                }, 1000); // 1 saniye bekleme (opsiyonel)
            }
        });
        
        webView.loadUrl("https://bist-bot-nxbsldnd77brg8whgatyxu.streamlit.app");
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
