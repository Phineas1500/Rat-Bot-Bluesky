import requests
from atproto import models, Client
import random
import csv
import json
import time
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

class ContentFilter:
    def __init__(self):
        # Sensitive topics and their related keywords
        self.sensitive_topics = {
            'death': [
                'rip', 'rest in peace', 'passed away', 'death', 'died', 'dead', 
                'condolences', 'funeral', 'mourning', 'tragedy', 'fatal', 'killed',
                'loss', 'gone too soon', 'in loving memory', 'memorial'
            ],
            'tragedy': [
                'accident', 'disaster', 'emergency', 'crisis', 'tragic', 'devastated',
                'devastating', 'horrible news', 'terrible news', 'catastrophe'
            ],
            'health': [
                'hospital', 'sick', 'illness', 'disease', 'cancer', 'surgery',
                'diagnosed', 'treatment', 'health', 'medical', 'recovery'
            ],
            'relationship': [
                'breakup', 'divorce', 'separated', 'break up', 'broke up',
                'breaking up', 'split up', 'splitting up', 'heartbreak'
            ],
            'grief': [
                'grief', 'grieving', 'sorry for your loss', 'heartbroken',
                'devastating', 'miss you', 'missing you'
            ]
        }
        
        # Combine all keywords into a single set for efficient checking
        self.all_keywords = set()
        for keywords in self.sensitive_topics.values():
            self.all_keywords.update(keywords)

    def preprocess_text(self, text):
        """Clean text for analysis"""
        # Convert to lowercase and remove extra whitespace
        text = text.lower().strip()
        # Remove special characters except spaces
        text = ''.join(char for char in text if char.isalnum() or char.isspace())
        # Split into words
        return text.split()

    def contains_sensitive_content(self, text):
        """
        Check if text contains sensitive content.
        Returns (bool, list of detected topics)
        """
        if not text:
            return False, []
        
        text_lower = text.lower()
        words = self.preprocess_text(text)
        detected_topics = set()

        # Check for exact matches and phrases
        for topic, keywords in self.sensitive_topics.items():
            for keyword in keywords:
                if keyword in text_lower:
                    detected_topics.add(topic)
                    
        # Look for word pairs (simplified bigram checking)
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if bigram in self.all_keywords:
                for topic, keywords in self.sensitive_topics.items():
                    if bigram in keywords:
                        detected_topics.add(topic)

        return len(detected_topics) > 0, list(detected_topics)

class BlueskyBot:
    def __init__(self, check_interval=60):
        self.list_uri = os.getenv('LIST_URI')
        self.username = os.getenv('BLUESKY_USERNAME')
        self.password = os.getenv('BLUESKY_PASSWORD')
        self.check_interval = int(os.getenv('CHECK_INTERVAL', '60'))
        if not all([self.list_uri, self.username, self.password]):
            raise ValueError("Missing required environment variables. Please check your .env file.")
        self.replied_posts_file = 'replied_posts.json'
        self.replied_posts = self.load_replied_posts()
        self.client = Client()
        # Fix: Use self.username and self.password instead of username and password
        self.client.login(self.username, self.password)
        self.content_filter = ContentFilter()

    def load_replied_posts(self):
        try:
            with open(self.replied_posts_file, 'r') as f:
                return set(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def save_replied_posts(self):
        with open(self.replied_posts_file, 'w') as f:
            json.dump(list(self.replied_posts), f)

    def fetch_latest_posts(self):
        base_url = "https://public.api.bsky.app/xrpc/app.bsky.feed.getListFeed"
        params = {
            'list': self.list_uri,
            'limit': 5
        }
        response = requests.get(base_url, params=params)

        if response.status_code == 200:
            return response.json().get('feed', [])
        else:
            print(f"Error fetching posts: {response.status_code}")
            return []

    def extract_reply_info(self, post):
        try:
            reply_info = post['reply']
            root = reply_info['root']
            parent = post['post']
            return parent, root
        except:
            return None, None

    def should_reply_to_post(self, post):
        """
        Determine if we should reply to a post based on content analysis.
        Returns (bool, str) - (should_reply, reason if not)
        """
        # Extract post text
        try:
            post_text = post['post']['record']['text']
        except KeyError:
            return True, "No text content"

        # Check for sensitive content
        has_sensitive_content, topics = self.content_filter.contains_sensitive_content(post_text)
        
        if has_sensitive_content:
            return False, f"Post contains sensitive topics: {', '.join(topics)}"
        
        return True, "Content appropriate for reply"

    def log_post_details(self, post):
        author = post.get('post', {}).get('author', {})
        author_handle = author.get('handle', 'unknown handle')
        display_name = author.get('displayName', 'unknown display name')
        post_uri = post.get('post', {}).get('uri', 'unknown uri')
        post_text = post.get('post', {}).get('record', {}).get('text', '')
        
        print(f"\nPost Analysis:")
        print(f"Author: {display_name} ({author_handle})")
        print(f"URI: {post_uri}")
        print(f"Content: {post_text[:100]}..." if len(post_text) > 100 else f"Content: {post_text}")
        
        should_reply, reason = self.should_reply_to_post(post)
        print(f"Should reply: {should_reply} - {reason}")

    def reply_to_post(self, post, reply_text, image_path):
        post_uri = post['post']['uri']

        # First check if we should reply
        should_reply, reason = self.should_reply_to_post(post)
        if not should_reply:
            print(f"Skipping reply to post {post_uri}: {reason}")
            return False

        # Skip if we've already replied to this post
        if post_uri in self.replied_posts:
            print(f"Already replied to post: {post_uri}")
            return False

        # Log the post details before replying
        self.log_post_details(post)

        # Rest of the reply logic remains the same...
        try:
            with open(image_path, 'rb') as img_file:
                img_data = img_file.read()
        except FileNotFoundError:
            print(f"Image file not found: {image_path}")
            return False
        except Exception as e:
            print(f"Error reading image file: {e}")
            return False

        try:
            parent, root = self.extract_reply_info(post)
            if parent and root:
                parent_strong_ref = {
                    "uri": parent['uri'],
                    "cid": parent['cid']
                }
                root_strong_ref = {
                    "uri": root['uri'],
                    "cid": root['cid']
                }
                self.client.send_image(
                    text=reply_text,
                    image=img_data,
                    image_alt="A cute dog",
                    reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent_strong_ref, root=root_strong_ref)
                )
            else:
                parent_strong_ref = {
                    "uri": post['post']['uri'],
                    "cid": post['post']['cid']
                }
                root_strong_ref = parent_strong_ref
                self.client.send_image(
                    text=reply_text,
                    image=img_data,
                    image_alt="A cute dog",
                    reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent_strong_ref, root=root_strong_ref)
                )

            self.replied_posts.add(post_uri)
            self.save_replied_posts()
            print(f"Successfully replied to post: {post_uri}")
            return True

        except Exception as e:
            print(f"Error sending reply: {e}")
            return False

    def get_random_content(self):
        x = random.randint(1, 514)
        with open('twitter_data.csv', mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if int(row['ID']) == x:
                    return row['Local Image Path'], row['Reply Text']
        return None, None

    def run(self):
        print(f"Bot started. Checking for new posts every {self.check_interval} seconds...")
        print("Content filtering is enabled - checking for sensitive topics...")
        
        while True:
            try:
                posts = self.fetch_latest_posts()
                new_replies = 0

                for post in posts:
                    img_path, reply_text = self.get_random_content()
                    
                    if img_path and reply_text:
                        if self.reply_to_post(post, reply_text, img_path):
                            new_replies += 1
                            time.sleep(2)
                    else:
                        print(f"Could not find random content")

                if new_replies > 0:
                    print(f"Replied to {new_replies} new posts")
                else:
                    print("No new posts to reply to")

                time.sleep(self.check_interval)

            except Exception as e:
                print(f"Error in main loop: {e}")
                print("Waiting 30 seconds before retrying...")
                time.sleep(30)

# Usage
if __name__ == "__main__":
    try:
        bot = BlueskyBot()
        bot.run()
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please make sure your .env file is properly configured.")
    except Exception as e:
        print(f"Error starting bot: {e}")