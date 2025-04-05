from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class User:
    """Standardized user data model."""
    id: str
    username: str
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    followers_count: Optional[int] = None
    following_count: Optional[int] = None
    description: Optional[str] = None
    platform: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname,
            'avatar': self.avatar,
            'followers_count': self.followers_count,
            'following_count': self.following_count,
            'description': self.description,
            'platform': self.platform
        }

@dataclass
class Comment:
    """Standardized comment data model."""
    id: str
    content: str
    user: Optional[User] = None
    created_at: Optional[datetime] = None
    likes_count: int = 0
    parent_id: Optional[str] = None
    replies: List['Comment'] = field(default_factory=list)
    platform: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'content': self.content,
            'user': self.user.to_dict() if self.user else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'likes_count': self.likes_count,
            'parent_id': self.parent_id,
            'replies': [reply.to_dict() for reply in self.replies],
            'platform': self.platform
        }

@dataclass
class Post:
    """Standardized post data model."""
    id: str
    title: Optional[str] = None
    content: Optional[str] = None
    media_urls: List[str] = field(default_factory=list)
    user: Optional[User] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    views_count: int = 0
    url: Optional[str] = None
    comments: List[Comment] = field(default_factory=list)
    platform: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'media_urls': self.media_urls,
            'user': self.user.to_dict() if self.user else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'likes_count': self.likes_count,
            'comments_count': self.comments_count,
            'shares_count': self.shares_count,
            'views_count': self.views_count,
            'url': self.url,
            'comments': [comment.to_dict() for comment in self.comments],
            'platform': self.platform
        }

@dataclass
class SearchResult:
    """Standardized search result data model."""
    keyword: str
    posts: List[Post] = field(default_factory=list)
    total_count: int = 0
    platform: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'keyword': self.keyword,
            'posts': [post.to_dict() for post in self.posts],
            'total_count': self.total_count,
            'platform': self.platform
        } 