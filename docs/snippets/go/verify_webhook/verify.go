// VerifyWebhook: check a DekernAI webhook delivery (WHK-02). The runner is main.go.
package main

// docs:start
import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"strconv"
	"strings"
)

// VerifyWebhook reports whether the DekernAI-Signature header matches the raw body and is
// within the time window. Pass now as time.Now().Unix() and tolerance as 300.
func VerifyWebhook(secret, header string, body []byte, now, tolerance int64) bool {
	var timestamp int64 = -1
	var signatures []string
	for _, part := range strings.Split(header, ",") {
		key, value, found := strings.Cut(strings.TrimSpace(part), "=")
		if !found {
			return false
		}
		switch key {
		case "t":
			if timestamp >= 0 || value == "" || strings.Trim(value, "0123456789") != "" {
				return false
			}
			n, err := strconv.ParseInt(value, 10, 64)
			if err != nil {
				return false
			}
			timestamp = n
		case "v1":
			signatures = append(signatures, value)
		}
	}
	if timestamp < 0 || len(signatures) == 0 {
		return false
	}
	if now-timestamp > tolerance || timestamp-now > tolerance {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(strconv.FormatInt(timestamp, 10) + "."))
	mac.Write(body)
	expected := []byte(hex.EncodeToString(mac.Sum(nil)))
	for _, s := range signatures {
		if hmac.Equal(expected, []byte(s)) {
			return true
		}
	}
	return false
}

// docs:end
