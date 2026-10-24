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
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)
        webView.clearCache(false)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val target = request?.url?.toString().orEmpty()
                // Keep same-origin navigation inside the WebView; hand anything
                // else (Telegram deep links, docs) to the system browser.
                if (target.isBlank() || target.startsWith(baseUrl)) return false
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
        }
        webView.webChromeClient = android.webkit.WebChromeClient()
    }

    private fun url(page: String): String = "$baseUrl$page"

    private fun configureBottomNavigation() {
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
            .setMessage("Botun web adresini girin (https:// ile başlamalı).")
            .setView(wrap)
            .setPositiveButton("Kaydet") { _, _ ->
                val v = input.text.toString().trim()
                if (v.startsWith("https://") || v.startsWith("http://")) {
                    saveBaseUrl(v)
                    toast("Kaydedildi")
                    binding.webView.loadUrl(url(PAGE_SCREENER))
                } else {
                    toast("Adres https:// ile başlamalı")
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

        private const val PAGE_SCREENER = "/ui/screener"
        private const val PAGE_WATCHLIST = "/ui/watchlist"
        private const val PAGE_PORTFOLIO = "/ui/portfolio"
        private const val PAGE_ALERTS = "/ui/alerts"
    }
}
