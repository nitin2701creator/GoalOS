<?php
/**
 * Plugin Name: GoalOS Abandoned Cart Bridge
 * Description: Sends abandoned-cart and recovery events from Abandoned Cart Lite to GoalOS in real time.
 * Version:     1.0.0
 * Author:      GoalOS
 * License:     GPL-2.0-or-later
 * Requires PHP: 7.4
 *
 * INSTALLATION:
 *   1. Copy this file to wp-content/plugins/goalos-abandoned-cart-bridge/
 *   2. Activate in WordPress admin -> Plugins
 *   3. Configure: Settings -> GoalOS Bridge
 *   4. Requires: Abandoned Cart Lite for WooCommerce (active)
 */

if (!defined('ABSPATH')) {
    exit;
}

class GoalOS_Abandoned_Cart_Bridge {

    /** @var string Option key for the GoalOS webhook URL */
    const OPT_URL = 'goalos_bridge_url';

    /** @var string Option key for the bearer token */
    const OPT_SECRET = 'goalos_bridge_secret';

    /** @var string Option key for notified cart IDs (serialized array) */
    const OPT_NOTIFIED = 'goalos_bridge_notified';

    /** @var int HTTP timeout in seconds */
    const TIMEOUT = 10;

    public function __construct() {
        // Core hook: fires when Abandoned Cart Lite changes a cart status.
        // Parameters: ($cart_status, $user_id, $user_email, $cart_hash, $cart_id).
        add_action('woocommerce_ac_status_change_cart', array($this, 'on_status_change'), 10, 5);

        // Also hook into cart recovery events if available.
        add_action('woocommerce_ac_cart_recovered', array($this, 'on_cart_recovered'), 10, 2);

        // WP-Cron fallback: periodically check for newly abandoned carts.
        add_action('goalos_check_abandoned_carts', array($this, 'cron_check_abandoned'));
        add_action('goalos_check_recovered_carts', array($this, 'cron_check_recovered'));

        // Admin settings page.
        add_action('admin_menu', array($this, 'add_settings_page'));
        add_action('admin_init', array($this, 'register_settings'));

        // Register activation/deactivation hooks via register_activation_hook.
        register_activation_hook(__FILE__, array($this, 'on_activate'));
        register_deactivation_hook(__FILE__, array($this, 'on_deactivate'));
    }

    /* ================================================================
     * Activation / Deactivation
     * ================================================================ */

    public function on_activate() {
        if (!wp_next_scheduled('goalos_check_abandoned_carts')) {
            wp_schedule_event(time(), 'goalos_abandoned_cart_interval', 'goalos_check_abandoned_carts');
        }
        if (!wp_next_scheduled('goalos_check_recovered_carts')) {
            wp_schedule_event(time(), 'goalos_recovered_cart_interval', 'goalos_check_recovered_carts');
        }

        // Register custom cron intervals.
        add_filter('cron_schedules', array($this, 'add_cron_intervals'));

        // Initialize notified array.
        if (!get_option(self::OPT_NOTIFIED)) {
            update_option(self::OPT_NOTIFIED, array());
        }
    }

    public function on_deactivate() {
        wp_clear_scheduled_hook('goalos_check_abandoned_carts');
        wp_clear_scheduled_hook('goalos_check_recovered_carts');
    }

    public function add_cron_intervals($schedules) {
        $schedules['goalos_abandoned_cart_interval'] = array(
            'interval' => 60,
            'display'  => __('Every 60 seconds (GoalOS Bridge)', 'goalos-bridge'),
        );
        $schedules['goalos_recovered_cart_interval'] = array(
            'interval' => 120,
            'display'  => __('Every 2 minutes (GoalOS Recovery)', 'goalos-bridge'),
        );
        return $schedules;
    }

    /* ================================================================
     * Core hook: WooCommerce Abandoned Cart Lite status change
     * ================================================================ */

    /**
     * Fires when Abandoned Cart Lite changes a cart's status.
     *
     * @param string $cart_status  New status: 'abandoned', 'recovered', etc.
     * @param int    $user_id     WordPress user ID (0 for guests).
     * @param string $user_email  Customer email (may be empty for guests).
     * @param string $cart_hash   Hash of the cart contents.
     * @param int    $cart_id     Abandoned cart record ID in the plugin's DB.
     */
    public function on_status_change($cart_status, $user_id, $user_email, $cart_hash, $cart_id) {
        $url = $this->get_url();
        if (!$url) {
            return;
        }

        error_log(sprintf(
            '[GoalOS Bridge] Status change: cart_id=%d status=%s email=%s',
            $cart_id,
            $cart_status,
            $user_email
        ));

        if ($cart_status === 'abandoned') {
            $this->send_abandoned_cart($cart_id, $user_id, $user_email);
        } elseif ($cart_status === 'recovered') {
            $this->send_recovered_cart($cart_id, $user_id, $user_email);
        }
    }

    /**
     * Cart recovered hook (if Abandoned Cart Lite fires it).
     */
    public function on_cart_recovered($cart_id, $user_id) {
        $url = $this->get_url();
        if (!$url) {
            return;
        }
        $user = $user_id ? get_userdata($user_id) : false;
        $email = $user ? $user->user_email : '';
        $this->send_recovered_cart($cart_id, $user_id, $email);
    }

    /* ================================================================
     * WP-Cron fallback: detect abandoned carts from the plugin DB
     * ================================================================ */

    /**
     * Check the Abandoned Cart Lite database for newly abandoned carts
     * that the hook might have missed, and send them to GoalOS.
     *
     * Abandoned Cart Lite stores abandoned carts in a table like:
     *   {prefix}woocommerce_ac_abandoned_cart
     *
     * Columns: id, user_id, user_email, abandoned_cart_info,
     *          abandoned_cart_time, status, etc.
     */
    public function cron_check_abandoned() {
        $url = $this->get_url();
        if (!$url) {
            return;
        }

        global $wpdb;
        $table = $wpdb->prefix . 'woocommerce_ac_abandoned_cart';

        // Check if the table exists.
        if ($wpdb->get_var("SHOW TABLES LIKE '{$table}'") !== $table) {
            return;
        }

        // Find carts abandoned in the last 3 minutes that we haven't notified about.
        $threshold = gmdate('Y-m-d H:i:s', time() - 180);
        $notified  = $this->get_notified_ids();

        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery
        $rows = $wpdb->get_results($wpdb->prepare(
            "SELECT id, user_id, user_email, abandoned_cart_info, abandoned_cart_time
             FROM {$table}
             WHERE status = 'abandoned'
               AND abandoned_cart_time > %s
             ORDER BY abandoned_cart_time DESC
             LIMIT 50",
            $threshold
        ));

        if (empty($rows)) {
            return;
        }

        foreach ($rows as $row) {
            $cart_id = (int) $row->id;
            if (in_array($cart_id, $notified, true)) {
                continue;
            }

            $this->send_abandoned_cart(
                $cart_id,
                (int) $row->user_id,
                $row->user_email,
                $row->abandoned_cart_info,
                $row->abandoned_cart_time
            );
        }
    }

    /**
     * Check for recovered carts that we haven't notified about.
     */
    public function cron_check_recovered() {
        $url = $this->get_url();
        if (!$url) {
            return;
        }

        global $wpdb;
        $table = $wpdb->prefix . 'woocommerce_ac_abandoned_cart';

        if ($wpdb->get_var("SHOW TABLES LIKE '{$table}'") !== $table) {
            return;
        }

        $notified = $this->get_notified_ids();

        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery
        $rows = $wpdb->get_results(
            "SELECT id, user_id, user_email
             FROM {$table}
             WHERE status = 'recovered'
             ORDER BY id DESC
             LIMIT 20"
        );

        if (empty($rows)) {
            return;
        }

        foreach ($rows as $row) {
            $cart_id = (int) $row->id;
            $recovery_key = 'recovered_' . $cart_id;
            if (in_array($recovery_key, $notified, true)) {
                continue;
            }

            $this->send_recovered_cart(
                $cart_id,
                (int) $row->user_id,
                $row->user_email
            );
        }
    }

    /* ================================================================
     * Send abandoned cart to GoalOS
     * ================================================================ */

    /**
     * Build and send an abandoned-cart event to GoalOS.
     *
     * @param int         $cart_id     Plugin's cart record ID.
     * @param int         $user_id     WordPress user ID.
     * @param string      $user_email  Customer email.
     * @param string|null $cart_info   Serialized cart info from the plugin DB.
     * @param string|null $abandoned_at Timestamp from the plugin DB.
     */
    private function send_abandoned_cart(
        $cart_id,
        $user_id,
        $user_email,
        $cart_info = null,
        $abandoned_at = null
    ) {
        // If cart_info not provided, try to load from DB.
        if ($cart_info === null) {
            $cart_info = $this->load_cart_info_from_db($cart_id);
        }

        $cart_data = maybe_unserialize($cart_info);
        if (!is_array($cart_data)) {
            $cart_data = array();
        }

        // Parse cart items from the plugin's data format.
        $items = $this->parse_cart_items($cart_data);

        // Calculate total.
        $total = 0.0;
        foreach ($items as $item) {
            $total += (float) ($item['line_total'] ?? 0);
        }

        // Get user info.
        $first_name = '';
        $last_name  = '';
        $phone      = '';
        if ($user_id > 0) {
            $user = get_userdata($user_id);
            if ($user) {
                $first_name = $user->first_name;
                $last_name  = $user->last_name;
                $phone      = get_user_meta($user_id, 'billing_phone', true);
                if (empty($user_email)) {
                    $user_email = $user->user_email;
                }
            }
        }

        // Get billing info from user meta if available.
        if ($user_id > 0 && empty($phone)) {
            $phone = get_user_meta($user_id, 'billing_phone', true);
        }

        // If we still don't have a name, try billing first/last.
        if (empty($first_name) && $user_id > 0) {
            $first_name = get_user_meta($user_id, 'billing_first_name', true);
            $last_name  = get_user_meta($user_id, 'billing_last_name', true);
        }

        // Abandoned-at timestamp.
        if (empty($abandoned_at)) {
            $abandoned_at = gmdate('c');
        } elseif (is_string($abandoned_at) && strpos($abandoned_at, 'T') === false) {
            // Convert MySQL datetime to ISO 8601.
            $abandoned_at = gmdate('c', strtotime($abandoned_at . ' UTC'));
        }

        $payload = array(
            'event_type'    => 'cart.abandoned',
            'source'        => 'abandoned_cart_lite',
            'cart_id'       => (string) $cart_id,
            'customer_id'   => $user_id,
            'customer_name' => trim($first_name . ' ' . $last_name),
            'customer_email' => $user_email,
            'customer_phone' => $phone,
            'currency'      => get_woocommerce_currency(),
            'cart_total'    => $total,
            'abandoned_at'  => $abandoned_at,
            'cart_items'    => $items,
        );

        $response = $this->post_to_goalos($url, $payload);

        if ($response && $response['code'] >= 200 && $response['code'] < 300) {
            $this->mark_notified($cart_id);
            error_log(sprintf(
                '[GoalOS Bridge] Sent abandoned cart %d — HTTP %d',
                $cart_id,
                $response['code']
            ));
        } else {
            error_log(sprintf(
                '[GoalOS Bridge] FAILED to send cart %d — HTTP %s',
                $cart_id,
                $response ? $response['code'] : 'timeout'
            ));
        }
    }

    /* ================================================================
     * Send recovered cart to GoalOS
     * ================================================================ */

    private function send_recovered_cart($cart_id, $user_id, $user_email) {
        $cart_info = $this->load_cart_info_from_db($cart_id);
        $cart_data = maybe_unserialize($cart_info);
        if (!is_array($cart_data)) {
            $cart_data = array();
        }

        $items = $this->parse_cart_items($cart_data);

        $total = 0.0;
        foreach ($items as $item) {
            $total += (float) ($item['line_total'] ?? 0);
        }

        $first_name = '';
        $last_name  = '';
        $phone      = '';
        if ($user_id > 0) {
            $user = get_userdata($user_id);
            if ($user) {
                $first_name = $user->first_name;
                $last_name  = $user->last_name;
                $phone      = get_user_meta($user_id, 'billing_phone', true);
                if (empty($user_email)) {
                    $user_email = $user->user_email;
                }
            }
        }

        $payload = array(
            'event_type'    => 'cart.recovered',
            'source'        => 'abandoned_cart_lite',
            'cart_id'       => (string) $cart_id,
            'customer_id'   => $user_id,
            'customer_name' => trim($first_name . ' ' . $last_name),
            'customer_email' => $user_email,
            'customer_phone' => $phone,
            'currency'      => get_woocommerce_currency(),
            'cart_total'    => $total,
            'abandoned_at'  => gmdate('c'),
            'cart_items'    => $items,
        );

        $response = $this->post_to_goalos($url, $payload);

        if ($response && $response['code'] >= 200 && $response['code'] < 300) {
            $this->mark_notified('recovered_' . $cart_id);
            error_log(sprintf(
                '[GoalOS Bridge] Sent recovery for cart %d — HTTP %d',
                $cart_id,
                $response['code']
            ));
        }
    }

    /* ================================================================
     * Parse cart items from plugin data
     * ================================================================ */

    /**
     * Parse the cart items array from Abandoned Cart Lite's data format.
     *
     * The plugin stores cart data in different formats depending on version.
     * Common format: array of cart item hashes => cart item data.
     *
     * @param array $cart_data Unserialized cart info from the plugin.
     * @return array Normalized array of cart items.
     */
    private function parse_cart_items($cart_data) {
        $items = array();

        // The plugin typically stores items as:
        // array( 'cart_item_hash' => array(
        //     'product_id' => ..., 'quantity' => ..., etc.
        // ))
        foreach ($cart_data as $key => $value) {
            if (!is_array($value)) {
                continue;
            }

            // Skip non-cart-item keys.
            if (isset($value['product_id'])) {
                $product_id   = (int) ($value['product_id'] ?? 0);
                $variation_id = (int) ($value['variation_id'] ?? 0);
                $quantity     = (int) ($value['quantity'] ?? 1);

                // Get product name and price.
                $product = wc_get_product($product_id);
                $name    = '';
                $sku     = '';
                $price   = 0.0;

                if ($product) {
                    $name = $product->get_name();
                    $sku  = $product->get_sku();
                    if ($variation_id > 0) {
                        $var = wc_get_product($variation_id);
                        if ($var) {
                            $name  = $var->get_name();
                            $sku   = $var->get_sku();
                            $price = (float) $var->get_price();
                        }
                    } else {
                        $price = (float) $product->get_price();
                    }
                }

                $items[] = array(
                    'product_id'   => $product_id,
                    'variation_id' => $variation_id,
                    'sku'          => $sku,
                    'product_name' => $name,
                    'quantity'     => $quantity,
                    'unit_price'   => $price,
                    'line_total'   => $price * $quantity,
                );
            }
        }

        return $items;
    }

    /* ================================================================
     * Load cart info from plugin DB
     * ================================================================ */

    private function load_cart_info_from_db($cart_id) {
        global $wpdb;
        $table = $wpdb->prefix . 'woocommerce_ac_abandoned_cart';

        if ($wpdb->get_var("SHOW TABLES LIKE '{$table}'") !== $table) {
            return null;
        }

        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery
        $row = $wpdb->get_row($wpdb->prepare(
            "SELECT abandoned_cart_info FROM {$table} WHERE id = %d",
            $cart_id
        ));

        return $row ? $row->abandoned_cart_info : null;
    }

    /* ================================================================
     * HTTP transport
     * ================================================================ */

    /**
     * POST JSON to the GoalOS abandoned-cart webhook endpoint.
     *
     * @param string $url     GoalOS webhook URL.
     * @param array  $payload Event payload.
     * @return array|null Array with 'code' and 'body' keys, or null on failure.
     */
    private function post_to_goalos($url, $payload) {
        $secret = $this->get_secret();
        if (!$secret) {
            error_log('[GoalOS Bridge] GOALOS_ABANDONED_CART_WEBHOOK_SECRET not set — skipping.');
            return null;
        }

        $response = wp_remote_post($url, array(
            'timeout' => self::TIMEOUT,
            'headers' => array(
                'Content-Type'  => 'application/json',
                'Authorization' => 'Bearer ' . $secret,
            ),
            'body' => wp_json_encode($payload),
        ));

        if (is_wp_error($response)) {
            error_log('[GoalOS Bridge] HTTP error: ' . $response->get_error_message());
            return null;
        }

        return array(
            'code' => wp_remote_retrieve_response_code($response),
            'body' => wp_remote_retrieve_body($response),
        );
    }

    /* ================================================================
     * Helpers
     * ================================================================ */

    private function get_url() {
        return get_option(self::OPT_URL, '');
    }

    private function get_secret() {
        return get_option(self::OPT_SECRET, '');
    }

    private function get_notified_ids() {
        $ids = get_option(self::OPT_NOTIFIED, array());
        return is_array($ids) ? $ids : array();
    }

    private function mark_notified($cart_id) {
        $ids = $this->get_notified_ids();
        if (!in_array($cart_id, $ids, true)) {
            $ids[] = $cart_id;
            // Keep only the last 5000 entries to prevent unbounded growth.
            if (count($ids) > 5000) {
                $ids = array_slice($ids, -5000);
            }
            update_option(self::OPT_NOTIFIED, $ids, false);
        }
    }

    /* ================================================================
     * Admin settings page
     * ================================================================ */

    public function add_settings_page() {
        add_options_page(
            'GoalOS Bridge',
            'GoalOS Bridge',
            'manage_woocommerce',
            'goalos-bridge',
            array($this, 'render_settings_page')
        );
    }

    public function register_settings() {
        register_setting('goalos_bridge_options', self::OPT_URL);
        register_setting('goalos_bridge_options', self::OPT_SECRET);
    }

    public function render_settings_page() {
        ?>
        <div class="wrap">
            <h1>GoalOS Abandoned Cart Bridge</h1>
            <p>Sends abandoned-cart events from Abandoned Cart Lite to GoalOS.</p>
            <form method="post" action="options.php">
                <?php settings_fields('goalos_bridge_options'); ?>
                <table class="form-table">
                    <tr>
                        <th scope="row">GoalOS Webhook URL</th>
                        <td>
                            <input type="url"
                                   name="<?php echo esc_attr(self::OPT_URL); ?>"
                                   value="<?php echo esc_attr(get_option(self::OPT_URL, '')); ?>"
                                   class="regular-text"
                                   placeholder="https://goalos.duckdns.org/api/v1/webhooks/abandoned-cart" />
                            <p class="description">Full URL to the GoalOS abandoned-cart webhook endpoint.</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">Webhook Secret (Bearer Token)</th>
                        <td>
                            <input type="password"
                                   name="<?php echo esc_attr(self::OPT_SECRET); ?>"
                                   value="<?php echo esc_attr(get_option(self::OPT_SECRET, '')); ?>"
                                   class="regular-text"
                                   autocomplete="off" />
                            <p class="description">Must match <code>GOALOS_ABANDONED_CART_WEBHOOK_SECRET</code> on the GoalOS server.</p>
                        </td>
                    </tr>
                </table>
                <?php submit_button('Save Settings'); ?>
            </form>
            <h2>Test Connection</h2>
            <p>
                <a href="<?php echo wp_nonce_url(
                    admin_url('admin.php?action=goalos_test_bridge'),
                    'goalos_test_bridge'
                ); ?>" class="button">Send Test Event</a>
            </p>
        </div>
        <?php
    }
}

// Initialize.
new GoalOS_Abandoned_Cart_Bridge();
