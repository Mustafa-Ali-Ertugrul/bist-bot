package com.bistbot.prototype

import android.annotation.SuppressLint
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.bistbot.prototype.databinding.ActivityMainBinding

/**
 * BIST Bot operator console.
 *
 * Loads the real server-rendered UI (Flask + Stitch templates) — the same pages a
 * desktop browser gets. The bundled assets HTML files were a UI prototype with
 * hard-coded demo data; they are no longer loaded.
 *
 * The base URL is user-configurable (Settings tab) and persisted in SharedPreferences,
 * so changing the server address does not require rebuilding the APK.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val handler = Handler(Looper.getMainLooper())

    private val prefs by lazy { getSharedPreferences(PREFS, MODE_PRIVATE) }

    private val baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL)?.trimEnd('/').orEmpty()

    private fun saveBaseUrl(value: String) {
        prefs.edit().putString(KEY_BASE_URL, value.trimEnd('/')).apply()
    }

    private fun resetBaseUrl() {
        prefs.edit().remove(KEY_BASE_URL).apply()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        configureWebView(binding.webView)
        configureBottomNavigation()
        if (baseUrl.isBlank()) {
            showError("Sunucu adresi tanımlı değil. Alarmlar sekmesine basılı tutarak girin.")
        } else {
            binding.webView.loadUrl(url(PAGE_SCREENER))
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) binding.webView.goBack()
                else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView(webView: WebView) {
        webView.setBackgroundColor(Color.TRANSPARENT)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            // The operator console is session-cookie based; persist it so the
            // phone does not re-login on every cold start.
            databaseEnabled = true
            cacheMode = WebSettings.LOAD_DEFAULT
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) forceDark = WebSettings.FORCE_DARK_ON
        }
        // Login survives app restarts.
        CookieManager.getInstance().setAcceptCookie(true)
        // Third-party cookies are off: only our own origin needs the session.
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)
        webView.clearCache(false)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val target = request?.url?.toString().orEmpty()
                // Keep same-origin navigation inside the WebView; hand anything
                // else (Telegram deep links, docs) to the system browser.
                // Compare hosts, not prefixes: "app.example.com.evil.com" must
                // never count as our own origin.
                val sameOrigin = try {
                    request?.url?.host != null && request.url.host == Uri.parse(baseUrl).host
                } catch (_: Exception) {
                    false
                }
                if (target.isBlank() || sameOrigin) return false
                return try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(target)))
                    true
                } catch (_: Exception) {
                    false
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                updateBottomNavigation(url.orEmpty())
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: android.webkit.WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                val isMainFrame = request?.isForMainFrame ?: false
                if (!isMainFrame) return
                showOfflinePage(request?.url?.toString().orEmpty())
            }
        }
        webView.webChromeClient = android.webkit.WebChromeClient()
    }

    /**
     * Offline / unreachable-server page. Without it the WebView shows the raw
     * Chromium error and the user cannot get back to a working page from the app.
     */
    private fun showOfflinePage(failedUrl: String) {
        val retryTarget = if (baseUrl.isNotBlank()) failedUrl.ifBlank { url(PAGE_MARKET) } else ""
        val retry = if (retryTarget.isBlank()) "about:blank" else retryTarget
        val html = """
            <!DOCTYPE html>
            <html lang="tr"><head><meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1"/>
            <style>
              body{margin:0;padding:24px;background:#06090A;color:#E6E8EE;
                   font-family:sans-serif;line-height:1.5}
              h1{font-size:1.25rem;margin:0 0 .5rem}
              p{color:#8B90A0;font-size:.9rem}
              button{margin-top:1rem;padding:.6rem 1rem;border:0;border-radius:.5rem;
                     background:#48DDBC;color:#10141A;font-weight:700;font-size:.9rem}
            </style></head>
            <body>
              <h1>Sunucuya ulaşılamadı</h1>
              <p>Bağlantıyı kontrol edin. Sorun sürerse Alarmlar sekmesine basılı tutarak
                 sunucu adresini güncelleyin.</p>
              <button onclick="location.href='$retry'">Yeniden dene</button>
            </body></html>
        """.trimIndent()
        binding.webView.loadDataWithBaseURL(baseUrl.takeIf { it.isNotBlank() }, html, "text/html", "utf-8", null)
    }

    private fun url(page: String): String = "$baseUrl$page"

    private fun configureBottomNavigation() {
        binding.navMarket.setOnClickListener { open(PAGE_MARKET) }
        binding.navDashboard.setOnClickListener { open(PAGE_SCREENER) }
        binding.navSignals.setOnClickListener { open(PAGE_WATCHLIST) }
        binding.navAnalysis.setOnClickListener { open(PAGE_PORTFOLIO) }
        binding.navSettings.setOnClickListener { openSettings() }
        binding.navSettings.setOnLongClickListener {
            showSettingsPanel()
            true
        }
        updateBottomNavigation(url(PAGE_SCREENER))
    }

    /** Alerts page first; connection panel if URL is blank or on long-press. */
    private fun openSettings() {
        if (baseUrl.isBlank()) {
            showSettingsPanel()
        } else {
            open(PAGE_ALERTS)
        }
    }

    private fun open(page: String) {
        if (baseUrl.isBlank()) {
            showSettingsPanel()
            return
        }
        binding.webView.loadUrl(url(page))
    }

    /**
     * Server URLs must be https. Plain http is accepted only for loopback
     * development (adb tunnels / local dev servers on 127.0.0.1, ::1 or
     * localhost) so session cookies never travel in cleartext off-device.
     */
    private fun isAllowedServerUrl(raw: String): Boolean {
        val v = raw.trim()
        if (v.startsWith("https://", ignoreCase = true)) return true
        if (!v.startsWith("http://", ignoreCase = true)) return false
        val host = Uri.parse(v).host?.trim()?.lowercase()?.removeSurrounding("[", "]")
        return host == "127.0.0.1" || host == "localhost" || host == "::1"
    }

    /**
     * Minimal in-WebView server configuration. The console is behind a login, so
     * a broken base URL would otherwise leave the user with no way back in.
     */
    private fun showSettingsPanel() {
        val current = baseUrl.ifBlank { DEFAULT_BASE_URL }
        val input = EditText(this).apply {
            setText(current)
            hint = "https://sunucu-ornegi.com"
            setSingleLine()
            setTextColor(Color.WHITE)
        }
        val pad = (16 * resources.displayMetrics.density).toInt()
        val wrap = FrameLayout(this).apply {
            setPadding(pad, pad, pad, pad)
            addView(input)
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle("Sunucu adresi")
            .setMessage("Botun web adresini girin (https:// ile başlamalı; http yalnızca 127.0.0.1/localhost için).")
            .setView(wrap)
            .setPositiveButton("Kaydet") { _, _ ->
                val v = input.text.toString().trim()
                if (isAllowedServerUrl(v)) {
                    saveBaseUrl(v)
                    toast("Kaydedildi")
                    binding.webView.loadUrl(url(PAGE_SCREENER))
                } else {
                    toast("Adres https:// ile başlamalı (http yalnızca 127.0.0.1/localhost)")
                }
            }
            .setNeutralButton("Varsayılan") { _, _ ->
                resetBaseUrl()
                toast("Varsayılan adres geri alındı")
                binding.webView.loadUrl(url(PAGE_SCREENER))
            }
            .setNegativeButton("İptal", null)
            .create()
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.parseColor("#1A1C1E")))
        dialog.show()
    }

    private fun updateBottomNavigation(current: String) {
        val items = mapOf(
            binding.navMarket to PAGE_MARKET,
            binding.navDashboard to PAGE_SCREENER,
            binding.navSignals to PAGE_WATCHLIST,
            binding.navAnalysis to PAGE_PORTFOLIO,
            binding.navSettings to PAGE_ALERTS
        )
        items.forEach { (item, page) ->
            setBottomNavigationItemState(item, current.contains(page))
        }
    }

    private fun setBottomNavigationItemState(item: TextView, active: Boolean) {
        val activeColor = Color.parseColor("#48DDBC")
        val inactiveColor = Color.parseColor("#8B90A0")
        val color = if (active) activeColor else inactiveColor
        item.setTextColor(color)
        item.background = getDrawable(
            if (active) R.drawable.bottom_nav_item_active else R.drawable.bottom_nav_item_inactive
        )
        item.compoundDrawableTintList = ColorStateList.valueOf(color)
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    private fun showError(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        binding.webView.apply { stopLoading(); destroy() }
        super.onDestroy()
    }

    companion object {
        private const val PREFS = "bistbot"
        private const val KEY_BASE_URL = "base_url"

        /** Overridable at build time: ./gradlew -PBIST_BOT_BASE_URL=... */
        private const val DEFAULT_BASE_URL = BuildConfig.BASE_URL

        private const val PAGE_MARKET = "/ui/market"
        private const val PAGE_SCREENER = "/ui/screener"
        private const val PAGE_WATCHLIST = "/ui/watchlist"
        private const val PAGE_PORTFOLIO = "/ui/portfolio"
        private const val PAGE_ALERTS = "/ui/alerts"
    }
}
