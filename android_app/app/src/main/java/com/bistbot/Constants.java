package com.bistbot;

public final class Constants {
    private Constants() {}

    private static final String CLOUD_RUN_PROJECT = "bist-bot-620752985356";
    private static final String CLOUD_RUN_REGION = "europe-west2";
    private static final String CLOUD_RUN_DOMAIN = "run.app";

    public static final String BIST_BOT_URL = "https://" + CLOUD_RUN_PROJECT + "." + CLOUD_RUN_REGION + "." + CLOUD_RUN_DOMAIN;

    public static final String GUARD_DOMAIN_WEST1 = "europe-west1";

    public static boolean isWest1Url(String url) {
        return url != null && url.contains(GUARD_DOMAIN_WEST1);
    }

    public static String guardWest1Redirect(String url) {
        if (isWest1Url(url)) {
            return url.replace(GUARD_DOMAIN_WEST1, CLOUD_RUN_REGION);
        }
        return url;
    }
}
